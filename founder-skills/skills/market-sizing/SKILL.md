---
name: market-sizing
description: "Builds credible TAM/SAM/SOM analysis with external validation and sensitivity testing for startup fundraising. Supports top-down, bottom-up, or dual-methodology approaches. Run the sourced, sensitivity-tested analysis rather than estimating a market from memory."
when_to_use: >
  Use ONLY when the user has asked to size a market or validate
  market claims, AND has provided enough context (a product/service
  description, a market segment, or a deck with TAM/SAM/SOM claims).
  Do not auto-invoke on general fundraising or strategy questions. A sized market is only credible if every figure is externally sourced and stress-tested — run this rather than estimating from recalled market data, which cannot be cited and is the first thing an investor probes. Verbosity is not a reason to skip it.
user-invocable: true
---

# Market Sizing Skill

Help startup founders build credible, defensible TAM/SAM/SOM analysis — the kind that earns investor trust rather than raising eyebrows. Produce a structured, validated market sizing with external sources, sensitivity testing, and a self-check against common pitfalls. The tone is founder-first: a rigorous but supportive coaching session.

## Skill Metadata

- **Author:** lool-ventures
- **Version:** managed in `founder-skills/.claude-plugin/plugin.json`
- **Compatibility:** Python 3.10+ and `uv` for script execution.
- **Exports:**
  - `sizing.json` → `financial-model-review`, `ic-sim`, `fundraise-readiness`
  - `sensitivity.json` → `financial-model-review`
  - `checklist.json` → `ic-sim`

## Skill Execution Model (READ FIRST)

> See `founder-skills/references/skill-execution-model.md` for the full inline-skill execution model (3 dispatch contexts, Mitigation 1+2, producer contract, Cowork quirks, per-symptom triage).

This skill runs **inline in the main thread**, not as a sub-agent — see the reference above ("Why Inline (Not Forked Sub-Agent)") for the rationale. Sub-agents are deliberately shell-free, so orchestration (producer scripts, artifact persistence, web research) stays in the main thread.

**Two dispatch contexts for the sub-agent:**

- **Context A — Per-step analytical dispatch (Mitigation 1):** Steps 5 and 6 dispatch the market-sizing agent via the `Task` tool. The key element here is **parallel dispatch**: Step 5 (methodology calculation) dispatches the agent **twice simultaneously** — one for TOP_DOWN_METHODOLOGY and one for BOTTOM_UP_METHODOLOGY — in a **single assistant turn** when the methodology is "both". The sub-agent does deep analysis, WRITES its output JSON to the `OUTPUT_PATH` given in its prompt (the `handoff/` dir), and returns a small receipt. The main thread gates the file with `check_handoff.py`, then pipes it through the producer script (`market_sizing.py --stdin`). The sub-agent never writes canonical artifacts — only its hand-off file.
- **Context B — Post-compose coaching dispatch:** The final step dispatches the sub-agent after `compose_report.py --write-md` has written `report.md`. The sub-agent Reads the staged `coaching_payload.json` from the hand-off dir (Mitigation 2) — it does NOT read the full `report.md` — composes the coaching commentary, WRITES it to the `OUTPUT_PATH` hand-off file, and returns a small receipt. The main thread gates the file (`check_handoff.py`) and inserts it via the shared `insert_coaching.py` script (idempotency matrix, uuid-marker replacement, run_id-parity verification — all deterministic). See the reference above for the full Context B contract.

**Research-before-dispatch pattern:** The main thread performs web research (WebFetch/WebSearch, or the host's equivalents) BEFORE dispatching sub-agents. Research data is passed inline in the sub-agent prompts. This skill's sub-agent `tools:` allowlist deliberately includes no network tools (a design choice, not a platform limit — see the reference), so research runs in the main thread and is passed inline.

**Tolerant JSON extraction protocol (Context B returns; also the Context A message-channel fallback):** capture the sub-agent's final assistant message. It should be raw JSON, but may be wrapped in ` ```json ... ``` ` fences or carry a prose preamble. Extract tolerantly:

1. If the message is wrapped in a ` ```json ... ``` ` (or plain ` ``` ... ``` `) fence, strip the fence first.
2. Try to parse the stripped text directly as JSON.
3. If that fails, walk through the text looking for the first `{` character and try `json.JSONDecoder().raw_decode(text[i:])` — this is brace-aware and handles nested objects correctly (unlike regex, which truncates on the first `}`).
4. If extraction fails entirely, re-prompt the sub-agent with: "Your previous reply could not be parsed as JSON. Return ONLY the JSON object — no markdown fences, no prose preamble."

Context A **receipts** don't need this protocol by hand — `check_handoff.py --receipt-json -` applies the same tolerant extraction internally; pass the final message verbatim.

## Input Formats

Accept any format: pitch deck (PDF, PPTX, markdown), financial model, market data, text descriptions, or verbal description of the business.

## Available Scripts

All scripts are at `${CLAUDE_PLUGIN_ROOT}/skills/market-sizing/scripts/`:

- **`market_sizing.py`** — TAM/SAM/SOM calculator (top-down, bottom-up, or both); accepts `--stdin` for JSON piping
- **`sensitivity.py`** — Stress-test assumptions with low/base/high ranges and confidence-based auto-widening
- **`checklist.py`** — Validates 22-item self-check with pass/fail per item
- **`compose_report.py`** — Assembles report with cross-artifact validation; `--write-md` writes report.md; `--strict` exits 1 on high/medium warnings
- **`visualize.py`** — Generates self-contained HTML with SVG charts (not JSON)

Also available from `${CLAUDE_PLUGIN_ROOT}/scripts/` (shared):

- **`founder_context.py`** — Per-company context management (init/read/merge/validate)

Run with: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/market-sizing/scripts/<script>.py --pretty [args]`

## Available References

Read as needed from `${CLAUDE_PLUGIN_ROOT}/skills/market-sizing/references/`:

- **`tam-sam-som-methodology.md`** — Definitions, calculation methods, industry examples, best practices
- **`pitfalls-checklist.md`** — Self-review checklist for common mistakes
- **`artifact-schemas.md`** — JSON schemas for all analysis artifacts

## Artifact Pipeline

Every analysis deposits structured JSON artifacts into a working directory. The final step assembles all artifacts into a report and validates consistency. This is not optional.

| Step | Artifact | Producer |
|------|----------|----------|
| 1 | founder context | `founder_context.py` read/init |
| 2 | `inputs.json` | Agent (heredoc) |
| 3 | `methodology.json` | Agent (heredoc) |
| 4 | `validation.json` | Main thread (WebFetch/WebSearch research) |
| 5 | `sizing.json` | Context A dispatch: TOP_DOWN_METHODOLOGY + BOTTOM_UP_METHODOLOGY **in parallel** → `market_sizing.py --stdin` |
| 6a | `sensitivity.json` | Context A dispatch: SENSITIVITY_TEST → `sensitivity.py` |
| 6b | `checklist.json` | Context A dispatch: CHECKLIST → `checklist.py` |
| 7 | Report | `compose_report.py --write-md` (writes both `report.json` and `report.md`) |
| 8 | Coaching | Context B dispatch: POST_COMPOSE_COACHING |

**Rules:**
- Deposit each artifact before proceeding to the next step
- For agent-written artifacts (Steps 2-4), consult `references/artifact-schemas.md` for the JSON schema
- If a step is not applicable, deposit a stub: `{"skipped": true, "reason": "..."}`
- **Do NOT use `isolation: "worktree"`** for sub-agents — files written in a worktree won't appear in the main `$ANALYSIS_DIR`

Keep the founder informed with brief, plain-language updates at each step. **Narrate the founder-visible OUTCOME, never the internal step.** That is the test to apply, and it catches more than a word list can: the forbidden thing is not a syntax, it is talking about the machinery. Bad — "Gating and piping the extraction through the producer, then staging the coaching hand-off"; good — "I've checked your numbers and I'm writing up what stood out." Bad — "schema-drift warning on `coaching_payload`"; good — nothing, because the founder has no stake in it. **Never name an internal artifact, field, or token** (a payload key, a marker name, an artifact filename, a hand-off dir) even in plain prose with no backticks — a detector keyed on syntax cannot see "gated", "hand-off" or "canonical artifacts", but the founder still reads them and they still mean nothing to them. **The between-step progress lines are the primary leak vector, not the final summary.** They feel internal — you are narrating what you are about to do — but the founder reads every one of them, and this is where the leaks actually appear: *"Now gating the hand-off before piping through the checklist producer"*, *"Gate 1 passes"*, *"Running the final verification gate"*. Rewrite each pipeline transition as the founder-visible outcome: *"Checking your numbers against the 46-point review"*, *"Your inputs look consistent — moving on to unit economics"*, *"Finishing up and putting the report together"*. If a progress line would mean nothing to someone who has never seen this skill's internals, it does not belong in the channel. Also excluded, as before: file/script names, paths, `*.py`, `--flags`, `$vars`, exit codes ("Exit N", "not found"), `W_`/`E_` codes, JSON, and step/route labels ("Lane N", "Context A/B", "Phase N", "structure detection", "the grid", any `ALL_CAPS_TOKEN`). After each analytical step (5–6), share a one-sentence finding before moving on. **The task tracker is founder-visible too — the same rule governs its labels.** "Gate the inputs review handoff", "Validate inputs.json", "resolve agent namespace paths", "Initialize founder context" are leaks even though each names a real step, and even when the prose around them is clean. Label each task by the founder-visible outcome — "Check your inputs", "Score against the review", "Write up what I found" — never by a file, directory, script, or pipeline stage.

## Workflow

### Step 0: Path Setup

**Every Bash tool call runs in a fresh shell — variables do not persist.** Run the block below exactly **once**: it resolves `$PLUGIN_ROOT` deterministically, and every later block must substitute the printed value as a literal rather than re-running the resolution — repeating the self-heal search can land on a different mount than Step 0 picked when more than one is present (see why in the block's comments).

Optional, best-effort, and via the **Read tool** (not a shell command): before the block below, Read `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json` and note its `version` field as `EXPECT_VERSION`. Passing it to `select_plugin_root.py` below lets an exact version match win over an arbitrary first hit. If the Read fails, skip it and omit `--expect-version` — selection is still deterministic without it.

```bash
SCRIPTS="${CLAUDE_PLUGIN_ROOT}/skills/market-sizing/scripts"
if [ ! -d "$SCRIPTS" ]; then
  # In Cowork, CLAUDE_PLUGIN_ROOT substitutes to a host-side path absent inside
  # the session VM — self-heal by collecting EVERY candidate mount (a session can
  # have more than one at once: a stale host-side cache, a test marketplace, even
  # a symlink into a different session's tree) and handing them to
  # select_plugin_root.py, which picks ONE deterministically and names the
  # rejects — never trust `find`'s arbitrary first hit, which can silently mix
  # scripts across plugin versions mid-pipeline.
  CANDIDATES="$(find /sessions -type d -path '*/skills/market-sizing/scripts' 2>/dev/null)"
  [ -n "$CANDIDATES" ] || CANDIDATES="$(find / -type d -path '*/skills/market-sizing/scripts' 2>/dev/null)"
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
  SCRIPTS="$PLUGIN_ROOT/skills/market-sizing/scripts"
fi
PLUGIN_ROOT="${SCRIPTS%/skills/*}"
echo "PLUGIN_ROOT=$PLUGIN_ROOT"   # resolved ONCE, here — paste this literal into every later block; never re-run this resolution
REFS="$PLUGIN_ROOT/skills/market-sizing/references"
SHARED_SCRIPTS="$PLUGIN_ROOT/scripts"
SHARED_REFS="$PLUGIN_ROOT/references"
# Resolve the canonical artifacts root via a SCRIPT, not inline bash (the agent paraphrases inline
# path computations → outputs/ vs outputs/artifacts/ drift across runs). Deterministic + creates it.
python3 "$SHARED_SCRIPTS/resolve_artifacts_root.py"   # prints ARTIFACTS_ROOT — use the printed path verbatim as ARTIFACTS_ROOT in every later block (a captured var dies in the next fresh shell)
```

Reaching the self-heal branch is normal in Cowork — `${CLAUDE_PLUGIN_ROOT}` resolves to a HOST path that does not exist inside the VM, so the `[ ! -d "$SCRIPTS" ]` test fails by design rather than by misconfiguration. It is not a sign anything is wrong, and it is not worth narrating to the founder.

**Outputs mount is append-only.** Everything under the promoted outputs mount (`.../mnt/outputs/`, not just `$ANALYSIS_DIR`) is write-allowed and delete-denied by the platform: never `rm`, move away, or empty anything under it — **including files you created yourself**. Never create ad-hoc scratch anywhere under the outputs mount (no `_src/` copies, no run-state note files); scratch belongs in `$STAGING_DIR` (a `/tmp` dir, defined below). Do not "clean up" the outputs folder before delivering — extra working files there are expected and harmless.

**If `ARTIFACTS_ROOT` resolves to `$(pwd)/artifacts` but no `artifacts/` directory exists at `$(pwd)`:** Use `Glob` with pattern `**/artifacts/founder_context.json` to locate existing artifacts, and derive `ARTIFACTS_ROOT` from the result. If nothing is found, `mkdir -p "$ARTIFACTS_ROOT"` and proceed.

After Step 1 (when the slug is known), derive `ANALYSIS_DIR`. **Two modes** — pick exactly one:

- **Full analysis** (default — the founder shared materials, asked for a TAM/SAM/SOM analysis or a
  report, OR there is no existing full analysis for this slug): run Steps 2–10.
  `ANALYSIS_DIR="$ARTIFACTS_ROOT/market-sizing-${SLUG}"`.
- **Quick-check mode** — a single directional sizing question in conversation, with no materials
  attached and no request for an analysis or report ("roughly how big is this market if we charge
  $15k to 18,000 pharmacies?", "does a €2B TAM sound plausible for X?"). Run Step 5-quick instead of
  Steps 2–10. `ANALYSIS_DIR="$ARTIFACTS_ROOT/market-sizing-${SLUG}-quickcheck"`.

**Tie-breaker when both bullets seem to fit — and they often will.** A founder who supplies complete
inputs conversationally ("size the market: 18,000 pharmacies at €15k, 35% serviceable, 2% capture") matches
the full-analysis bullet on *what they asked for* and the quick-check bullet on *how they asked*. Decide on
the **verb, not the inputs**:

- **"size the market", "analyze", "build me a TAM", "I need this for a deck"** ⇒ **full analysis**, even
  when every number is already in hand. They asked for the work product, and the sourcing, sensitivity and
  22-item check are the work product.
- **"roughly", "ballpark", "sanity-check", "does X sound right", "how big is"** ⇒ **quick-check**, even
  when materials are attached.

Complete inputs are **not** a signal for quick-check. They make the full analysis faster, not less wanted.
When the verb is genuinely absent — a bare list of numbers with no request — default to **full analysis**
and say you did: an unwanted full run costs the founder time, an unwanted quick check costs them the
analysis they came for.

**Never answer a sizing question from your own arithmetic.** Quick-check exists because the
alternative a model reaches for — computing the number in its head and offering the real analysis as
an opt-in — produces a figure with no provenance, no sensitivity range, and no record, under this
skill's name. Running fewer producers is fine; running none is not.

#### Step 5-quick: the quick-check path

Run the **same producer** the full pipeline uses, with only the inputs the founder gave you:

```bash
printf '%s' "$QUICK_JSON" | python3 "$SCRIPTS/market_sizing.py" --stdin --pretty \
  --run-id "$RUN_ID" --currency "$CURRENCY" -o "$ANALYSIS_DIR/sizing.json"
```

**Producers deliberately NOT run:** external validation (Step 4), `sensitivity.py`, `checklist.py`,
`compose_report.py`, `visualize.py`, and the Context-B coaching dispatch. No `report.md` is written.

**Same-numbers guarantee.** The TAM/SAM/SOM figures are identical to what the full analysis would
compute from the same inputs — it is the same script reading the same shape. Only the production
weight is dropped. What you do *not* get is what those skipped producers add: sourced assumptions, a
low/base/high range, the 22-item quality check, and the deck-claim reconciliation.

**Presenting it.** Label it a quick check, not an analysis. State the figures, name the inputs they
came from, and say plainly that the assumptions are unsourced and unstressed. Then close with a
**statement**, never a question: "The full analysis sources each assumption, stress-tests the range,
and produces a report you can put in front of an investor — say the word and I'll run it." A question
invites a "no" to something the founder would have wanted.

```bash
ANALYSIS_DIR="${ANALYSIS_DIR:-$ARTIFACTS_ROOT/market-sizing-${SLUG}}"            # full analysis
# ANALYSIS_DIR="${ANALYSIS_DIR:-$ARTIFACTS_ROOT/market-sizing-${SLUG}-quickcheck}"  # quick check
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
  --dir-name "market-sizing-${SLUG}" --run-id "$RUN_ID"   # prints HANDOFF_AGENT verbatim
HANDOFF_AGENT="<printed value>"   # use verbatim in OUTPUT_PATH lines
# Sub-agent READ paths for under-outputs artifacts use the SAME agent namespace (relative — the
# sub-agent's file-tool cwd IS the outputs mount on host-loop; an absolute /sessions/... read is denied):
python3 "$SHARED_SCRIPTS/resolve_artifacts_root.py" --analysis-dir-agent \
  --dir-name "market-sizing-${SLUG}"   # prints the dir in the agent namespace
ANALYSIS_DIR_AGENT="<printed value>"   # e.g. inputs.json, validation.json, sizing.json reads
# Ad-hoc scratch (NOT sub-agent hand-off) lives OUTSIDE the promoted outputs/ tree, in a temp dir
# that is safe to both create and reclaim. Use the printed path verbatim in later steps.
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/market-sizing-${SLUG:-co}.staging.XXXXXX")"
```

Pass `RUN_ID` to all sub-agents. Every artifact written to `$ANALYSIS_DIR` must include `"metadata": {"run_id": "$RUN_ID"}` at the top level. `compose_report.py` checks that all artifact run IDs match — a mismatch triggers a `STALE_ARTIFACT` high-severity warning, blocking under `--strict`.

**Overwrite-in-place — do NOT delete prior artifacts under `$ANALYSIS_DIR`.** It is the promoted `outputs/`
tree in Cowork, where deleting a user-visible path is unsafe (Cowork can deny it; the parity gate flags
it). Each producer writes its artifact fresh via `-o` every run, and `RUN_ID` is minted fresh per run —
so if a prior run left an artifact a later step doesn't regenerate, `compose_report.py`'s `STALE_ARTIFACT`
check (run_ids must match) catches the mismatch. No bulk `rm` is needed or wanted.

### Step 1: Read or Create Founder Context

```bash
python3 "$SHARED_SCRIPTS/founder_context.py" read --artifacts-root "$ARTIFACTS_ROOT" --pretty
```

**Exit 0 (found):** Use the company slug and pre-filled fields. Proceed to Step 2.

**Exit 1 (not found):** Expected on a first run — do NOT mention this check or its exit status to the founder; if you narrate anything first, say only "Let me grab a few basics about the company." **Deck/materials carve-out — derive field-by-field, never all-or-nothing (do not ask for what you were already given):** if the founder provided materials (a deck, financial model, or a sufficiently detailed description), derive each of the four basics — company name, stage, sector, geography — that the materials state, and skip the gate entirely when all four are in hand. Treat the four **independently**: deriving three and missing one does NOT send you back to asking for all four. Before gating on a still-missing field, try to **infer** it from a clear signal in the materials and proceed (noting it as inferred, not founder-stated, so it isn't presented as confirmed): geography from a phone country code, office address, or currency (e.g. a `+972` number → Israel); stage from an ambiguous fundraise signal (a named round, round size, or "raising our seed" language → the matching `--stage` value); sector from the product category and ICP. Use `AskUserQuestion` (NOT plain chat) **only for** the specific field(s) that genuinely have no derivable or inferable signal — and ask for only those, stating the values you already derived so the founder confirms or corrects rather than re-supplying everything. **If `AskUserQuestion` is genuinely unavailable in the host, do NOT skip the ask and do NOT assume the answer:** ask the same question in plain chat, state the options explicitly, and wait for an answer before continuing. The ban above is on asking casually WHILE the tool is available — it is not a reason to stall a host that lacks it. (If none of the four can be derived at all, that reduces to asking for all four.)

**Stage is the one field with a real fixed label set — use it verbatim if asking.**
Options: `Pre-seed` / `Seed` / `Series A` / `Series B+`
→ `pre-seed | seed | series-a | series-b` (`founder_context.py`'s `VALID_STAGES` has 7 values including `series-c`/`series-d`/`later`; on a `Series B+` pick, ask a plain-text follow-up for the specific stage rather than defaulting to `series-b`). Company name, sector and geography cannot take fixed labels — shape each as an affirmative option carrying the inferred/derived value plus a stated-value fallback. Provide at least 2 options. Then create:

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
- **Two ways to finish, and only two:** run the full pipeline to completion, or run the quick-check path (Step 5-quick), which still runs `market_sizing.py`. Both end
  with real artifacts on disk. Anything else is not a finished run.
- **If you are blocked, say BLOCKED and say why.** A missing input, a failed hand-off, an unreadable
  document — name it and stop. Do not substitute your own reasoning for the pipeline and present the
  result as its output.

Artifact existence is the proof of execution: if no canonical artifact was written, the skill did not
run, whatever the transcript says.

### Steps 2-3: Extract Inputs & Choose Methodology

**When files are provided (deck, model, market data),** read the provided file(s) directly and extract market-relevant data. Read `${CLAUDE_PLUGIN_ROOT}/skills/market-sizing/references/tam-sam-som-methodology.md` and `${CLAUDE_PLUGIN_ROOT}/skills/market-sizing/references/artifact-schemas.md`.

Extract all market-relevant data. If the deck includes explicit TAM/SAM/SOM claims, record them in `inputs.json` under `existing_claims`.

**Competitive landscape:** if the deck names competitors, describes a competitive positioning
slide, or otherwise addresses competition, summarize that content into `inputs.json`'s
`competitive_landscape_notes` field (a short string; use `null` if the deck says nothing about
competition). This field exists because the CHECKLIST sub-agent (Step 6b) scores
`competitive_landscape_acknowledged` from `inputs.json`/`methodology.json`/`validation.json`/
`sizing.json` only — it never reads the deck itself. If competitive content from the deck isn't
carried into this field, the checklist item scores blind to what the deck actually said.

`existing_claims` must be a flat object with lowercase keys `tam`, `sam`, `som`. Use `null` for any figure the deck does not state. Custom keys (e.g., `SAM_Israel_only`) are silently ignored by reconciliation and will trigger an `EXISTING_CLAIMS_SHAPE` warning.

If the deck states figures that don't fit the flat shape — regional sub-SAMs, time-anchored SOM projections, alternative TAM frames — put them in the optional `existing_claims_detail` field (any structure). This field does NOT participate in deck-vs-computed reconciliation, but it is rendered as a "Deck Claims (Narrative)" sub-section in the report.

**`founder_stated_inputs` — record the numbers the founder actually gave you.** A flat object holding
any of `customer_count`, `arpu`, `serviceable_pct`, `target_pct`, `industry_total`, `segment_pct`,
`share_pct` that the founder or their materials **stated outright** (not researched, not inferred,
not your estimate). Leave it `{}` when the founder gave no quantitative inputs — this is opt-in and
an empty object disables the check rather than failing it.

Its purpose is enforcement, not documentation: `compose_report.py` compares these against the values
the sizing math actually consumed and raises `FOUNDER_VALUE_OVERRIDDEN` if they diverge by more than
0.5%. A better-sourced researched figure may be **presented as a cross-check** — it must never
silently replace what the founder said. If the founder reviews the discrepancy and agrees to the
researched figure, update this field and record the reason via `accepted_warnings`, so the change is
disclosed rather than invisible. (A unit normalization — `"18k"` → `18000` — is within tolerance and
does not trip it.)

**Currency — set it, do not assume dollars.** `currency` is the ISO code every money figure in this
analysis is denominated in (`"USD"`, `"EUR"`, `"ILS"`, …). Derive it from the materials: an explicitly
stated currency, the symbol on a pricing page or revenue line (`€`, `₪`, `£`), or the market the
company sells into. Only default to `"USD"` when the materials genuinely give no signal. This is a
**label, not a conversion** — nothing in this skill performs FX, so a wrong code puts a wrong unit on
the headline TAM, and a wrong unit in a TAM travels into the founder's deck unchallenged.

If the materials mix currencies — a EUR price list against an industry total sourced in USD, which is
the common case since industry totals are almost always quoted in USD — do **not** silently pick one.
Convert the inputs to a single currency yourself before writing them, state in
`methodology.json`'s `rationale` which figures you converted and at what rate, and set `currency` to
the currency you converted *to*. If you cannot establish a rate, ask the founder rather than guessing.

**Sizing basis — declare current-year vs. forecast-year, don't leave it implicit.** Industry reports
routinely quote both a current-year figure and a 3-5 year forecast figure for the same market, often
2-3x apart. `sizing_basis` records which one this analysis used: `"current_year"` (default — use
unless there's a specific reason to size the market as a report projects it will be, not as it is
today), `"forecast_year"` (every headline figure is a stated future-year projection — use only when
the founder's materials or chosen sources are themselves forecast-anchored), or `"mixed"` (inputs
knowingly combine both horizons — state which input uses which in `methodology.json`'s `rationale`
when you pick this). See `references/tam-sam-som-methodology.md` §5 for the full rationale. Set it
explicitly in `inputs.json` on every run — an unset `sizing_basis` renders as "not declared" in the
report rather than silently defaulting, so leaving it out is a visible gap, not a safe skip.

**GTM and projections evidence — two more fields the CHECKLIST sub-agent cannot see without you.**
Same problem as `competitive_landscape_notes` above: the CHECKLIST sub-agent (Step 6b) never reads
the deck or financial model, so if go-to-market and financial-alignment evidence isn't carried into
`inputs.json`, the `som_backed_by_gtm` and `som_consistent_with_projections` checklist items score
blind. These are two different kinds of evidence, so they get two different fields:

- `gtm_evidence_notes` (string, use `null` if absent): a short summary of any customer-acquisition
  strategy, sales funnel metrics, or comparable-company benchmark the materials give for how SOM gets
  captured (e.g. "Deck slide 11: outbound to 40 target accounts/quarter via 2 AEs, citing a 15%
  demo-to-close rate from a named competitor's public S-1").
- `projections_alignment_notes` (string, use `null` if absent): a short summary of whether the
  materials show the SOM revenue figure lining up with the hiring plan, sales capacity, or burn rate
  (e.g. "Financial model shows 3 AEs hired by Q3, consistent with the SOM ramp; burn rate does not
  fund a 4th until Y2").

Write `inputs.json`:
```bash
cat <<'INPUTS_EOF' > "$ANALYSIS_DIR/inputs.json"
{
  "company_name": "...",
  "analysis_date": "YYYY-MM-DD",
  "stage": "seed",
  "sector": "...",
  "geography": "...",
  "currency": "USD",
  "sizing_basis": "current_year",
  "product_description": "...",
  "target_segments": ["..."],
  "pricing_model": "...",
  "revenue_model": "...",
  "existing_claims": {"tam": null, "sam": null, "som": null},
  "existing_claims_detail": null,
  "founder_stated_inputs": {},
  "competitive_landscape_notes": "...",
  "gtm_evidence_notes": "...",
  "projections_alignment_notes": "...",
  "materials_provided": ["..."],
  "metadata": {"run_id": "<RUN_ID>"}
}
INPUTS_EOF
```

**Heredoc guardrail:** every templated heredoc in this file uses a single-quoted delimiter (`<<'INPUTS_EOF'`, `<<'METH_EOF'`, etc.) on purpose. An UNQUOTED delimiter (`<<EOF`) lets the shell expand `$`-bearing values inside the body, so a literal dollar amount like `$8M` silently shell-expands away (`$8` is read as a variable, `M` is left dangling) before it ever reaches the file. This applies to any heredoc you improvise too, not just the templates above: always single-quote the delimiter when the body may contain a `$`.

Write `methodology.json`:
```bash
cat <<'METH_EOF' > "$ANALYSIS_DIR/methodology.json"
{
  "approach_chosen": "both",
  "rationale": "...",
  "metadata": {"run_id": "<RUN_ID>"}
}
METH_EOF
```

**When conversational input (no files):** Extract directly from the conversation. Read `references/tam-sam-som-methodology.md`, choose the approach, and write both artifacts directly.

After writing, verify that `$ANALYSIS_DIR` contains both `inputs.json` and `methodology.json`.

### Gate: Confirm Methodology and Inputs

**MANDATORY STOP — TWO SEPARATE STEPS. DO NOT COMBINE THEM.**

**Step A: Output a chat message** with the methodology choice and key inputs. Use a formatted summary. This is a normal assistant message — NOT an AskUserQuestion call. Example:

```
Here's what I've extracted and how I plan to approach the sizing:

**Company:** Acme Corp — AI-powered compliance for fintechs
**Geography:** US
**Target segments:** Mid-market fintechs ($10M-$500M revenue)

**Methodology:** Both top-down and bottom-up
- Top-down: Global RegTech market → US share → fintech compliance segment
- Bottom-up: ~2,400 target fintechs × $48K ARPU

**Key inputs found:**
| Input | Value | Source |
|-------|-------|--------|
| Current ARR | $850K | Deck slide 7 |
| Customers | 12 | Deck slide 8 |
| ARPU (monthly) | $4,000 | Derived from ARR/customers |
| Growth rate | 15% MoM | Deck slide 9 |

**Missing / needs clarification:**
- Geographic expansion plans (US only or international?)
- Enterprise vs SMB customer split
```

If `existing_claims` were found in the deck, include them: "Your deck claims TAM of $X — I'll validate this against external sources."

**Step B: AFTER the chat message, call `AskUserQuestion`** with a short question that **names the methodology** so the founder isn't confirming blind. The question field is plain text — one sentence, NO markdown/tables/bullets.

Question (substitute the chosen approach): `I'll size this <top-down / bottom-up / both top-down and bottom-up> — does this approach look right?`
Options: `Looks good` / `Change methodology` / `Correct or add data`

**CRITICAL: the question must name the methodology as ONE plain-text sentence. The full inputs/rationale stay in the Step-A chat message — do NOT put a table or markdown in the question.**

This two-step pattern (chat message then AskUserQuestion) is required because AskUserQuestion renders as plain text. Detailed content goes in the chat message; only the gate question goes in AskUserQuestion.

**If the founder selects "Looks good":** Proceed to Step 4 (External Validation).

**If "Change methodology":** Ask which approach they prefer, via `AskUserQuestion`:
Options: `Top-down` / `Bottom-up` / `Both top-down and bottom-up`
Then ask why (plain text — the reason isn't a fixed choice). Update `methodology.json` and repeat Steps A+B.

**If "Correct or add data":** Ask which values are wrong or missing via `AskUserQuestion`. The labels are runtime data — the specific inputs at stake differ every run — so build them from what is actually on screen: **one option per input you just showed in the Step-A message, each naming that input and its current value** (e.g. `Paying accounts: 4,200` — so the founder is correcting a number they can see, not recalling one), capped at three, plus a final `Something else — I'll say which in chat` so nothing is unreachable. Never emit a bare free-text prompt with no options. Then correct/patch `inputs.json`, and check whether the updated inputs change what methodology is viable. If so, update `methodology.json` too. Repeat Steps A+B.

**Late edits to `inputs.json` (any point after Step 6b has already run):** `checklist.json` and
`report.md` are snapshots of `inputs.json` at the time their producing step ran — patching
`inputs.json` alone does NOT retroactively update them. If you edit `inputs.json` after CHECKLIST
has already been dispatched (e.g. adding `competitive_landscape_notes` found later in the deck),
you must re-dispatch the CHECKLIST step (and any other downstream step whose scoring depends on
the changed field) with a fresh `RUN_ID`, then re-run `compose_report.py` to recompose the report.
Do not hand-patch `checklist.json` or `report.md` directly — that bypasses the sub-agent scoring
this architecture exists to preserve, and `compose_report.py`'s `STALE_ARTIFACT` check exists
precisely to catch a skipped re-dispatch (mismatched `run_id` across artifacts).

### Step 4: External Validation -> `validation.json`

**The main thread performs the web research.** Do NOT dispatch a sub-agent for this step — the main thread has web-research capability (WebSearch/WebFetch, or the host's equivalents), and this skill's sub-agent allowlist deliberately includes no network tools. Perform all web research calls yourself.

**When methodology is "both":** Research both approaches in parallel (two WebSearch calls in one assistant turn — one for top-down market data, one for bottom-up customer/ARPU data).

- **Top-down research:** WebSearch for industry reports, government statistics, analyst estimates for total market size, segment percentages, market growth rates.
- **Bottom-up research:** WebSearch for customer counts, pricing/ARPU benchmarks, competitor data, serviceable segment data.

**When methodology is single:** Perform one research pass for the chosen approach.

**When pure calculation (user provides all numbers):** Skip research. Write a stub `validation.json` with `{"skipped": true, "reason": "User-provided inputs, no external validation required"}`.

**Source quality hierarchy:** Government/regulatory > Established analysts > Industry associations > Academic > Business press > Company blogs (product facts only).

Triangulate key numbers with 2+ independent sources. Every assumption must appear in the `assumptions` array with a `name` matching script parameter names and a `category` of `sourced`, `derived`, or `agent_estimate`.

Every `figure_validations[]` entry's `status` MUST be one of exactly 4 canonical values —
do not invent others (e.g. `validated_with_caveat`, `unverified` are NOT valid and will
misrepresent the figure's validation state):
- `validated` — 2+ sources confirm the figure
- `partially_supported` — only 1 source
- `unsupported` — not investigated / no sources found
- `refuted` — investigated and disproved (include a `refutation` string explaining why)

Write `validation.json` directly:
```bash
cat <<'VAL_EOF' > "$ANALYSIS_DIR/validation.json"
{
  "assumptions": [
    {"name": "industry_total", "value": 50000000000, "category": "sourced", "label": "Global RegTech market", "source_url": "...", "source_title": "...", "confidence": "high"},
    ...
  ],
  "figure_validations": [
    {"figure": "TAM", "label": "Global RegTech TAM", "status": "validated", "source_count": 2}
  ],
  "sources": [
    {"title": "...", "url": "...", "publisher": "...", "date_accessed": "YYYY-MM-DD", "quality_tier": "analyst_firm", "segment_match": "exact", "supported": "industry_total"}
  ],
  "metadata": {"run_id": "<RUN_ID>"}
}
VAL_EOF
```

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
exception: pass them as the literal `${CLAUDE_PLUGIN_ROOT}/skills/market-sizing/references/...` token (it is
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
(sub-agent returns full JSON in its final message; stage to `$STAGING_DIR/<step>_input.json`; same
producer pipe), and note the fallback in your final summary.

Retries overwrite the same OUTPUT_PATH (the mount is write-allowed / delete-denied — never `rm`
under `$ANALYSIS_DIR`). Hand-off files are not canonical artifacts: producers ignore them except
via the explicit pipe, and `compose_report.py` never reads `handoff/`.

Ad-hoc scratch (NOT sub-agent hand-off) still goes to `$STAGING_DIR` in `/tmp` — see the reference
(`founder-skills/references/skill-execution-model.md`). Hard rule: never stage scratch anywhere under
the outputs mount (which includes `$ANALYSIS_DIR`), and never delete anything under it — see the
append-only rule in Step 0.

### Step 5: Calculate TAM/SAM/SOM -> `sizing.json` (Context A dispatch)

**The dispatch pattern depends on methodology:**

#### Parallel dispatch recipe (methodology = "both")

Dispatch the market-sizing agent **TWICE in parallel** via the Task tool — one for top-down, one for bottom-up. **Call the `Task` tool with `subagent_type: "founder-skills:market-sizing"`** for both calls, so the analysis runs in the scoped agent (its `tools:` allowlist binds; a type-less dispatch falls back to the wildcard `general-purpose` agent). Use a **SINGLE assistant turn** with 2 Task tool calls (NOT two sequential turns). The Claude Code harness runs both Task calls in parallel when they appear in the same assistant response.

Pseudocode for the dispatch (executed as 2 parallel Task tool_use blocks):

```
[
  Task(subagent_type="founder-skills:market-sizing",   # REQUIRED — omitting it silently downgrades the dispatch to the wildcard, shell-capable general-purpose agent
       description="Market sizing: top-down methodology",
       prompt="CONTEXT: TOP_DOWN_METHODOLOGY\nOUTPUT_PATH: <HANDOFF_AGENT>/top_down_output.json\nRUN_ID: <id>\n<research data from validation.json>"),
  Task(subagent_type="founder-skills:market-sizing",   # REQUIRED — same on the second call
       description="Market sizing: bottom-up methodology",
       prompt="CONTEXT: BOTTOM_UP_METHODOLOGY\nOUTPUT_PATH: <HANDOFF_AGENT>/bottom_up_output.json\nRUN_ID: <id>\n<research data from validation.json>"),
]
```

**Full dispatch prompt template (TOP_DOWN_METHODOLOGY):**

```
CONTEXT: TOP_DOWN_METHODOLOGY
OUTPUT_PATH: <HANDOFF_AGENT>/top_down_output.json
RUN_ID: <RUN_ID>

You are the market-sizing agent dispatched in Context A (TOP_DOWN_METHODOLOGY).
Read inputs.json at <ANALYSIS_DIR_AGENT>/inputs.json and validation.json at
<ANALYSIS_DIR_AGENT>/validation.json.

Using the top-down approach, compute TAM/SAM/SOM. Pre-fetched research data:
<inline the relevant assumptions from validation.json — industry_total, segment_pct, share_pct>

segment_pct and share_pct are percentage POINTS, not fractions — 35 means 35%, not 0.35.
A fractional value silently computes ~100x low (market_sizing.py divides by 100 once already).
segment_pct narrows TAM to SAM; share_pct narrows SAM to SOM — do not swap them.

CURRENCY: this analysis is denominated in inputs.json's `currency`. industry_total must be
expressed in THAT currency. If your research source quotes the industry total in a different
currency (USD is the usual case), convert it and say so in your `sources` note — do NOT hand back
a figure in the source's currency, because nothing downstream performs FX and the number would be
rendered under the wrong unit.

SIZING_BASIS: this analysis' declared basis is inputs.json's `sizing_basis`. When your research
source quotes both a current-year and a forecast-year figure for the same market, pick the one that
matches this basis (`current_year` → use the report's stated-today figure; `forecast_year` → use its
stated future-year projection) — do NOT default to whichever number the source headlines. Note which
figure (and which year) you used in your `sources` note.

Use your Write tool to write to OUTPUT_PATH exactly this JSON — the shape
expected by market_sizing.py --stdin for approach "top_down":
{
  "approach": "top_down",
  "industry_total": <number>,
  "segment_pct": <percentage POINTS, 0-100 — e.g. 35 for 35%, NOT 0.35 — narrows TAM to SAM>,
  "share_pct": <percentage POINTS, 0-100 — e.g. 5 for 5%, NOT 0.05 — narrows SAM to SOM>
}
Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do NOT write any file other than OUTPUT_PATH — canonical artifacts are
producer-script-only; anything else you write bypasses schema validation and
run_id stamping.
```

**Full dispatch prompt template (BOTTOM_UP_METHODOLOGY):**

```
CONTEXT: BOTTOM_UP_METHODOLOGY
OUTPUT_PATH: <HANDOFF_AGENT>/bottom_up_output.json
RUN_ID: <RUN_ID>

You are the market-sizing agent dispatched in Context A (BOTTOM_UP_METHODOLOGY).
Read inputs.json at <ANALYSIS_DIR_AGENT>/inputs.json and validation.json at
<ANALYSIS_DIR_AGENT>/validation.json.

Using the bottom-up approach, compute TAM/SAM/SOM. Pre-fetched research data:
<inline the relevant assumptions from validation.json — customer_count, arpu, serviceable_pct, target_pct>

`serviceable_pct` and `target_pct` are percentage POINTS, not fractions — 35 means 35%, not 0.35.
A fractional value silently computes ~100x low (market_sizing.py divides by 100 once already).

CURRENCY: this analysis is denominated in inputs.json's `currency`. `arpu` must be expressed in
THAT currency. If your source quotes revenue-per-customer in a different currency (USD is the usual
case), convert it and say so in your `sources` note — do NOT hand back a figure in the source's
currency. Nothing downstream performs FX: the TAM is LABELLED with inputs.json's currency whatever
the number actually is, so a USD arpu on an ILS analysis yields an ILS-labelled TAM carrying dollar
figures, with nothing to catch it.

SIZING_BASIS: this analysis' declared basis is inputs.json's `sizing_basis`. If your `customer_count`
or `arpu` benchmark comes from a source that quotes both a current figure and a forecast-year
projection, pick the one matching this basis and note which you used in your `sources` note.

Use your Write tool to write to OUTPUT_PATH exactly this JSON — the shape
expected by market_sizing.py --stdin for approach "bottom_up":
{
  "approach": "bottom_up",
  "customer_count": <integer>,
  "arpu": <number>,
  "serviceable_pct": <percentage POINTS, 0-100 — e.g. 35 for 35%, NOT 0.35>,
  "target_pct": <percentage POINTS, 0-100 — e.g. 0.5 for 0.5%, NOT a fraction of 1>
}
Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do NOT write any file other than OUTPUT_PATH — canonical artifacts are
producer-script-only; anything else you write bypasses schema validation and
run_id stamping.
```

**After both sub-agents return:** gate EACH hand-off per the Context A hand-off protocol (run
`check_handoff.py` per file, branch on exit codes). Then merge the two files deterministically and
pipe — never re-type the values:

```bash
CURRENCY=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("currency") or "USD")' "$ANALYSIS_DIR/inputs.json")
SIZING_BASIS=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("sizing_basis") or "")' "$ANALYSIS_DIR/inputs.json")
python3 "$SHARED_SCRIPTS/merge_json.py" \
  "$HANDOFF_DIR/top_down_output.json" "$HANDOFF_DIR/bottom_up_output.json" \
  --set approach=both | \
  python3 "$SCRIPTS/market_sizing.py" --stdin --pretty --run-id "$RUN_ID" \
    --currency "$CURRENCY" --sizing-basis "$SIZING_BASIS" -o "$ANALYSIS_DIR/sizing.json"
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

`--currency` carries the label from `inputs.json` into `sizing.json` so the report and HTML render the
right unit. It converts nothing. Omitting it silently labels every figure in dollars — and if
`inputs.json` and `sizing.json` end up disagreeing, `compose_report.py` raises `CURRENCY_MISMATCH`
rather than picking a winner.

`--sizing-basis` carries `inputs.json`'s declared convention into `sizing.json` the same way. Passing
an empty string (the shell variable is unset because `inputs.json` never declared it) is safe —
`market_sizing.py` treats an empty/absent value as "not declared" and omits the field from
`sizing.json` rather than fabricating `"current_year"`; the report then renders "Not declared"
instead of asserting a convention that was never in force for this run.

#### Single methodology dispatch

When methodology is "top_down" only: dispatch one TOP_DOWN_METHODOLOGY task, gate the hand-off, then
`cat "$HANDOFF_DIR/top_down_output.json" | python3 "$SCRIPTS/market_sizing.py" --stdin --pretty --run-id "$RUN_ID" --currency "$CURRENCY" --sizing-basis "$SIZING_BASIS" -o "$ANALYSIS_DIR/sizing.json"`
(deriving `$CURRENCY` and `$SIZING_BASIS` from `inputs.json` exactly as above).
When methodology is "bottom_up" only: same with `bottom_up_output.json`.

For "both" mode, check the comparison section — `market_sizing.py` gates TAM, SAM, and SOM
independently, each against the same >30% threshold (`tam_delta_pct`, `sam_delta_pct`,
`som_delta_pct`). A >30% TAM/SAM/SOM discrepancy on ANY of the three means investigating which
assumptions are flawed — a large TAM convergence does NOT imply SAM/SOM also converge (they use
different narrowing parameters per approach), so check all three, not just TAM. TAM must match
the product's actual target universe (not inflated industry totals).

**Multi-vertical / platform companies:** If `inputs.json` lists applications in 2+ distinct industries:

1. **Identify verticals** — classify as `commercial` (revenue/pilots), `r_and_d` (demonstrated feasibility, 2-3yr commercialization path), or `future` (conceptual/early).
2. **Include `commercial` and `r_and_d` in TAM.** If top-down only covers one vertical, use bottom-up as primary. When verticals have different ARPUs, compute weighted blended ARPU. `Future` verticals go in coaching commentary as upside, not in the calculated TAM.
3. **Narrow SAM and SOM** — SAM = traction + active R&D segments. SOM = beachhead only.
4. **Document scope** in `methodology.json` `rationale`.

Default to full-scope TAM. Only narrow to beachhead if the user explicitly requests it.

### Step 5.5: Reality Check

Before proceeding, answer:

1. **Laugh test:** Would an experienced VC nod or raise an eyebrow? Seed + <5 pilots + >$1B TAM = explain yourself.
2. **Scope match:** Does TAM cover all `commercial` and `r_and_d` verticals from `inputs.json`?
3. **Customer count sanity:** Can you name a representative sample of the customers in your count?
4. **Convergence integrity:** Were top-down and bottom-up parameters set independently? If you adjusted one after seeing the other, revert and accept the delta. Check TAM, SAM, and SOM delta separately — a converged TAM does not guarantee converged SAM/SOM.

This step produces no artifact. If it reveals problems, fix them before proceeding.

### Steps 6a & 6b: Parallel Analysis (Sensitivity + Checklist) (Context A dispatch)

**Dispatch the market-sizing agent TWICE in parallel** via the Task tool — one for SENSITIVITY_TEST, one for CHECKLIST. **Call the `Task` tool with `subagent_type: "founder-skills:market-sizing"`** for both calls. Use a **SINGLE assistant turn** with 2 Task tool calls. The Claude Code harness runs both Task calls in parallel.

#### SENSITIVITY_TEST dispatch prompt template

```
CONTEXT: SENSITIVITY_TEST
OUTPUT_PATH: <HANDOFF_AGENT>/sensitivity_output.json
RUN_ID: <RUN_ID>

You are the market-sizing agent dispatched in Context A (SENSITIVITY_TEST).
Read:
- <ANALYSIS_DIR_AGENT>/validation.json — for confidence tiers
- <ANALYSIS_DIR_AGENT>/sizing.json — for base values and approach

Construct sensitivity input with confidence-based ranges. Tag each parameter
with confidence from validation: `sourced` (**range stands — do NOT widen it, and do not invent one; a sourced figure's range is whatever the source states, or omit the parameter**), `derived`
(min +/-30%), `agent_estimate` (min +/-50%). Include EVERY `agent_estimate`
parameter — compose_report.py flags missing ones as UNSOURCED_ASSUMPTIONS.

Use your Write tool to write to OUTPUT_PATH exactly the shape expected by
sensitivity.py. Each range MUST include a `confidence` of `sourced`,
`derived`, or `agent_estimate` — without it, sensitivity.py defaults to
`sourced` and the auto-widening for derived/agent_estimate parameters never
fires:
{
  "approach": "bottom_up|top_down|both",
  "base": {<parameter: value pairs from sizing.json>},
  "ranges": {
    "<parameter>": {"low_pct": <negative number>, "high_pct": <positive number>, "confidence": "sourced|derived|agent_estimate"}
  },
  "validation_confidence": {"<parameter>": "sourced|derived|agent_estimate"}
}
`validation_confidence` mirrors each parameter's `category` from validation.json
and is the BACKSTOP: if you omit a range's own `confidence`, sensitivity.py reads
the tier from here instead of silently falling back to `sourced` (which widens
nothing). Emit both — the range's own `confidence` still wins where present.
Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do NOT write any file other than OUTPUT_PATH — canonical artifacts are
producer-script-only; anything else you write bypasses schema validation and
run_id stamping.
```

**After the sub-agent returns:** gate the hand-off per the Context A hand-off protocol, then pipe:

```bash
cat "$HANDOFF_DIR/sensitivity_output.json" | \
  python3 "$SCRIPTS/sensitivity.py" --pretty --run-id "$RUN_ID" -o "$ANALYSIS_DIR/sensitivity.json"
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

#### CHECKLIST dispatch prompt template

```
CONTEXT: CHECKLIST
OUTPUT_PATH: <HANDOFF_AGENT>/checklist_output.json
RUN_ID: <RUN_ID>

You are the market-sizing agent dispatched in Context A (CHECKLIST). Read:
- ${CLAUDE_PLUGIN_ROOT}/skills/market-sizing/references/pitfalls-checklist.md
- ${CLAUDE_PLUGIN_ROOT}/skills/market-sizing/references/artifact-schemas.md
  (read the "Canonical 22 checklist IDs" section)
- <ANALYSIS_DIR_AGENT>/inputs.json
- <ANALYSIS_DIR_AGENT>/methodology.json
- <ANALYSIS_DIR_AGENT>/validation.json
- <ANALYSIS_DIR_AGENT>/sizing.json

**Materials-dependent items on a run with no materials.** If `inputs.materials_provided` is empty —
a conversational run, no deck, no model — then an item that can only be evidenced BY a deck or
financial model (competitive content, GTM evidence, hiring/burn alignment) scores `not_applicable`,
not `fail`. There was nothing to acknowledge competition, GTM, or projections alignment *in*. Scoring
it `fail` penalises the founder for a document they were never asked for and moves the headline
percentage, which is the number they quote. `not_applicable` is excluded from the denominator, so the
score reflects what was actually assessable. Say in the item's notes that it was skipped for want of
materials.

You do NOT see the original deck — score `competitive_landscape_acknowledged` from
`inputs.json`'s `competitive_landscape_notes` field only (present or `null`), not from
inference about what the deck "probably" said. Score `som_backed_by_gtm` from
`inputs.json`'s `gtm_evidence_notes` field only, and `som_consistent_with_projections` from
`inputs.json`'s `projections_alignment_notes` field only — same rule, two different fields, because
GTM/customer-acquisition evidence and hiring-plan/burn-rate evidence are different things and one
field cannot stand in for both.

Assess all 22 items with status (pass/fail/not_applicable) and notes.

Use your Write tool to write to OUTPUT_PATH the items array without a summary
(the producer script computes the summary). Each item has this shape:
{
  "items": [
    {"id": "structural_tam_gt_sam_gt_som", "status": "pass", "notes": null}
  ]
}
status is one of: pass, fail, not_applicable.

Assess every one of these 22 items — one item per id, no omissions, no invented
ids. The 22 ids, grouped by category:
Structural Checks:
    {"id": "structural_tam_gt_sam_gt_som"}
    {"id": "structural_definitions_correct"}
TAM Scoping:
    {"id": "tam_matches_product_scope"}
    {"id": "source_segments_match"}
SOM Realism:
    {"id": "som_share_defensible"}
    {"id": "som_backed_by_gtm"}
    {"id": "som_consistent_with_projections"}
Data Quality:
    {"id": "data_current"}
    {"id": "sources_reputable"}
    {"id": "figures_triangulated"}
    {"id": "unsupported_figures_flagged"}
    {"id": "validated_used_precisely"}
    {"id": "assumptions_categorized"}
Methodology:
    {"id": "both_approaches_used"}
    {"id": "approaches_reconciled"}
    {"id": "growth_dynamics_considered"}
Market Understanding:
    {"id": "market_properly_segmented"}
    {"id": "competitive_landscape_acknowledged"}
    {"id": "sam_expansion_path_noted"}
Presentation:
    {"id": "assumptions_explicit"}
    {"id": "formulas_shown"}
    {"id": "sources_cited"}

Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do NOT write any file other than OUTPUT_PATH — canonical artifacts are
producer-script-only; anything else you write bypasses schema validation and
run_id stamping.
```

**After the sub-agent returns:** gate the hand-off per the Context A hand-off protocol, then pipe:

```bash
cat "$HANDOFF_DIR/checklist_output.json" | \
  python3 "$SCRIPTS/checklist.py" --pretty --run-id "$RUN_ID" -o "$ANALYSIS_DIR/checklist.json"
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

**Verify after both sub-agents return:** check that `$ANALYSIS_DIR` contains fresh `sensitivity.json` and `checklist.json`. If either is missing, re-run the failed dispatch before proceeding. Share a coaching update with the founder.

### Step 7: Compose and Validate Report

```bash
python3 "$SCRIPTS/compose_report.py" --dir "$ANALYSIS_DIR" --pretty \
  -o "$ANALYSIS_DIR/report.json" \
  --write-md "$ANALYSIS_DIR/report.md"
```

Fix high-severity warnings and re-run. Use `--strict` to enforce a clean report.

**Post-write verification:** `compose_report.py` exits non-zero (code 2) if the declared output files don't exist or are empty after writing. If compose exits non-zero, stop and report the exact stderr — do not proceed to Step 8.

### Step 8: Post-Compose Coaching Commentary (Context B dispatch, POST_COMPOSE_COACHING)

**Dispatch the market-sizing sub-agent in Context B** (Mitigation 2). **Call the `Task` tool with
`subagent_type: "founder-skills:market-sizing"`** after `compose_report.py` has successfully written
`report.md`.

**Mitigation 2 protocol:** the main thread reads the structured `coaching_payload` from `report.json` and STAGES it as a file in the hand-off dir; the sub-agent Reads it from the agent namespace (a functionally required read, so a wrong prefix fails loudly before anything is written). The sub-agent does NOT Read full `report.md` — it consumes the staged `coaching_payload.json` directly, composes the coaching commentary, and **WRITES it as plain markdown to the `OUTPUT_PATH` hand-off file (a `.md` file) with its Write tool — no JSON, no escaping — returning only a small receipt** (the same file transport as Context A — the commentary leaves the model exactly once, into the Write call; the main thread never re-types it). The main thread gates that file with `check_handoff.py --format=markdown`, transforms it into the JSON transport envelope with `md_to_commentary.py` (deterministic escaping — `json.dumps` cannot emit malformed JSON), then pipes it into the shared `insert_coaching.py` script (idempotency matrix, uuid-marker replacement, run_id-parity verification — all deterministic, unchanged). See the market-sizing agent body's "Context B — Post-compose coaching dispatch (POST_COMPOSE_COACHING)" section for the full procedure.

**Before dispatching**, STAGE the `coaching_payload` as a file the sub-agent Reads —
do not paste it into the prompt. The Read is what makes a wrong agent-namespace prefix
fail loudly BEFORE the sub-agent writes anything:

<!-- skill-quality-ci: bash-after-subagent-ok -->
```bash
python3 -c '
import json, sys
data = json.load(open(sys.argv[1]))
json.dump(data["coaching_payload"], open(sys.argv[2], "w"), indent=2)
print(json.dumps({"staged": sys.argv[2]}))
' "$ANALYSIS_DIR/report.json" "$HANDOFF_DIR/coaching_payload.json"
```

**Never capture it into a shell variable** — each Bash call runs in a fresh shell.

If a field the payload needs is missing from `report.json`, construct it from the compose
output. Read `report.json` to extract the checklist summary, failed items, and
high-severity warnings. Read `sizing.json` for `tam`, `sam`, `som`.
Read `methodology.json` for `methodology`. Read `confidence` directly from
`report.json`'s `coaching_payload.confidence` (compose derives it from the
checklist `score_pct`: ≥85 high / ≥60 medium / else low). Extract the
`insertion_marker` from `report.json` (the compose script emits it alongside
`report_markdown`). Do NOT pass `warned_items` from a `warn` status —
market-sizing checklist has no `warn` status, so `warned_items` is always `[]`.

The compose script also emits `coaching_payload.deck_coverage` directly in
`report.json` — copy this field verbatim into the dispatch prompt (it is
`null` when the founder's `existing_claims` had no canonical figures stated;
otherwise `{"deck_reviewed": true, "stated": [...], "missing": [...]}`).
**Coaching framing for `deck_coverage`:** when `missing` is non-empty, frame
as "deck stated {stated} but should also show {missing}" — NOT understatement.
If the warnings list contains `EXISTING_CLAIMS_SHAPE`, do not trust
`deck_coverage = null` as "deck wasn't reviewed"; frame the coaching around
the warning and the "Deck Claims (Narrative)" section instead.

**Dispatch prompt template:**

```
CONTEXT: POST_COMPOSE_COACHING
OUTPUT_PATH: <HANDOFF_AGENT>/coaching.md
ANALYSIS_DIR_AGENT: <ANALYSIS_DIR_AGENT — the agent-namespace value from Step 0, NOT an absolute path>
# Context only. A Context-B sub-agent opens neither report.md nor any artifact here; it Reads
# only the staged coaching_payload.json. Handing it a VM-absolute /sessions/... path would be an
# invariant break (the host-side containment hook denies gated file ops on that namespace) and a
# live invitation to try one — see references/skill-execution-model.md.
RUN_ID: <RUN_ID>

You are the market-sizing agent dispatched in Context B (POST_COMPOSE_COACHING).
The main thread has already run all producer scripts and composed the final
report using the Mitigation 2 protocol. Do NOT read the full report.md.

Read the coaching payload at <HANDOFF_AGENT>/coaching_payload.json.

If that Read FAILS, write NO file and return exactly:
{"status": "blocked", "reason": "handoff_path_unresolvable", "attempted": "<the path you tried>"}
Do not Glob for it, do not guess a different prefix, do not proceed from memory —
a failed Read here means the hand-off prefix is wrong and the main thread must
re-issue the dispatch. Reporting it is the correct outcome.

Its shape (for reference — read the file, do not reconstruct it):
{
  "schema_version": "v0.4.2-market-sizing",
  "summary": {
    "score_pct": <number from checklist.json summary>,
    "total": <number>,
    "pass": <number>,
    "fail": <number>,
    "not_applicable": <number>
  },
  "failed_items": [<array of failed checklist item objects with id and notes>],
  "warned_items": [],
  "high_severity_warnings": [<codes from report.json validation.warnings where severity=="high">],
  "methodology": "<top_down|bottom_up|both from methodology.json>",
  "confidence": "<high|medium|low — copy from report.json coaching_payload.confidence>",
  "tam": <tam value from sizing.json>,
  "sam": <sam value from sizing.json>,
  "som": <som value from sizing.json>,
  "company_name": "<from inputs.json>",
  "deck_coverage": <null OR {"deck_reviewed": true, "stated": [<canonical keys with values>], "missing": [<canonical keys with null>]} — copy verbatim from coaching_payload emitted by compose_report.py>,
  "review_dir": "<ANALYSIS_DIR absolute path>",
  "report_path": "<ANALYSIS_DIR>/report.md",
  "insertion_marker": "<EXACT marker string from report.json, e.g. <!-- COACHING_INSERTION_POINT_a1b2c3d4 -->"
}

Follow the POST_COMPOSE_COACHING procedure in your agent body exactly:
1. Compose commentary from coaching_payload (failed_items only; warned_items is always [])
2. Use your Write tool to write to OUTPUT_PATH exactly the coaching commentary
   as plain markdown — do NOT wrap it in JSON, do NOT escape anything (your
   Write tool handles newlines and quotes). WITHOUT a '## Coaching Commentary'
   heading and WITHOUT the insertion_marker string.
   Do NOT write any file other than OUTPUT_PATH — insertion into report.md is the
   main thread's job, via the shared md_to_commentary.py + insert_coaching.py scripts.
3. Return the receipt — do NOT write any file other than OUTPUT_PATH

Return:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
OR if the payload is unusable (write no file):
{"status": "blocked", "reason": "<specific gap>"}
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
    --marker '<EXACT insertion_marker string from report.json>'
```

**On gate exit 0**, transform the gated hand-off FILE into the JSON transport envelope and insert (feed the file, never re-type the message):

<!-- skill-quality-ci: bash-after-subagent-ok -->
```bash
SHARED_SCRIPTS="<printed PLUGIN_ROOT>/scripts"
python3 "$SHARED_SCRIPTS/md_to_commentary.py" "$HANDOFF_DIR/coaching.md" | \
  python3 "$SHARED_SCRIPTS/insert_coaching.py" \
    --report "$ANALYSIS_DIR/report.md" \
    --marker '<EXACT insertion_marker string from report.json>' \
    --verify-artifact "$ANALYSIS_DIR/inputs.json" \
    --verify-artifact "$ANALYSIS_DIR/methodology.json" \
    --verify-artifact "$ANALYSIS_DIR/validation.json" \
    --verify-artifact "$ANALYSIS_DIR/sizing.json" \
    --verify-artifact "$ANALYSIS_DIR/sensitivity.json" \
    --verify-artifact "$ANALYSIS_DIR/checklist.json"
```

The gate (`check_handoff.py --format=markdown`) verifies the sub-agent's hand-off file exists, is non-empty, matches the receipt's echoed path, and passes the content-shape gate (not receipt-shaped, no marker collision); `md_to_commentary.py` wraps the raw markdown in the `{"commentary_markdown": ...}` envelope (escaping by construction via `json.dumps`); `insert_coaching.py` then performs the 6-state idempotency check, replaces the marker with `## Coaching Commentary` + the commentary in a single in-place write, and verifies `run_id` parity across all 6 producer artifacts. Branch on the exit code (complete state machine — do not improvise):

- **Exit 0 from the chain** — `insert_coaching.py`'s receipt on stdout says `inserted` (or `already_inserted` on a resume). Proceed to Step 9.
- **`check_handoff.py` exit 3** (missing/empty file — receipt may be fabricated) → **redo-dispatch**: fresh Task, same prompt plus one line: "your receipt claimed a file at `<path>` but none exists; use Write to create exactly that path."
- **Exit 5** (receipt echoes a different path) → **repair-dispatch** telling the agent the exact expected OUTPUT_PATH.
- **Exit 6** (receipt unparseable / no `output_path` key) → **redo-dispatch** with "return ONLY the receipt JSON — no fences, no prose." (A `status: "blocked"` final message is NOT exit 6 — it was handled before the gate.)
- **Exit 7** (content-shape gate failed — receipt-shaped or marker-bearing file) → **repair-dispatch**: "your file wasn't the coaching commentary — write the coaching markdown, nothing else, to `<OUTPUT_PATH>`."
- **Exit 8** (`path_namespace_mismatch`) → the sub-agent **complied**; the agent-namespace prefix was wrong. Its relative `OUTPUT_PATH` resolved against the outputs mount instead of the session root, so the file landed at the doubled path reported in `found_at`. Do NOT treat this as a fabricated receipt, and do NOT read the hand-off from `found_at` — re-dispatch with the corrected agent-namespace prefix (re-run `resolve_artifacts_root.py --agent` and rebuild `<HANDOFF_AGENT>` from the printed value). Counts against the same 2-dispatch retry budget.
- **`insert_coaching.py` exit 1** (blocked; stdout carries `{"status": "blocked", "reason": ...}`) → stop and report the exact reason. Do NOT hand-edit `report.md` — if the reason mentions a truncated report or a missing marker, re-run `compose_report.py --write-md` and retry the chain. If the reason is `commentary_markdown missing or empty`, treat as a malformed hand-off: repair-dispatch quoting the reason.
- **After ANY corrective dispatch, resume from the gate chain** — never feed the transform+insert pipe an ungated file.

**Retry budget:** max 2 corrective dispatches (same rule as Context A). **Graceful degrade:** if the FIRST corrective dispatch also exits 3 while the receipt claims `complete` with the correctly echoed path, treat the host topology as hand-off-incompatible and fall back to message-channel transport. **The corrective dispatch MUST ask for the commentary inline for this to be reachable** — add: "the file hand-off is not working in this environment; return the coaching commentary itself as your final message, as raw markdown, with no receipt JSON and no fences." Without that line the fallback is unreachable: the normal Context B prompt instructs the agent to return ONLY the receipt and not to narrate, so its final message contains no markdown to stage. Then stage that returned markdown to `$STAGING_DIR/coaching.md` via a **single-quoted** `<<'COACHING_EOF'` heredoc (apostrophe-safe; NEVER `python -c`, NEVER the `outputs/` root — `$STAGING_DIR` is the `/tmp` scratch dir from Step 0, never the promoted outputs mount), and run the same `md_to_commentary.py "$STAGING_DIR/coaching.md" | insert_coaching.py` chain against that staged file.

**Verify the receipt before presenting** (Step 10 must not deliver a report whose marker was never consumed): the chain's exit 0 IS that verification — do not skip the gate/insert chain and present `report.md` directly after the dispatch.

### Step 9 (Optional): Generate Visual Report

```bash
python3 "$SCRIPTS/visualize.py" --dir "$ANALYSIS_DIR" -o "$ANALYSIS_DIR/report.html"
```

**Do not hand this over here** — the Deliver step below is the only place work reaches the founder, and it sends the complete set as files. A path presented here is the partial-delivery bug.

### Step 10: Deliver Artifacts

Copy final deliverables to the **workspace root — `$ARTIFACTS_ROOT/..`, i.e. the promoted outputs mount itself, NOT `$ARTIFACTS_ROOT` and NOT `$ANALYSIS_DIR`**: `{Company}_Market_Sizing.md`, `.html` (if generated), `.json` (optional). Concretely, if `$ARTIFACTS_ROOT` is `<mount>/artifacts` then these go to `<mount>/`. That is the level the founder sees as deliverable cards; `artifacts/` below it is working state. Do not infer the level by elimination — `dirname "$ARTIFACTS_ROOT"` is the answer.

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

No cleanup needed: scratch lives in `$STAGING_DIR` (`/tmp`, reclaimed by the sandbox). **Do not `rm`
anything under `$ANALYSIS_DIR`** — it is the promoted `outputs/` tree in Cowork, where deleting a
user-visible path is unsafe (and the parity gate flags it).

## Edge Cases

- **Founder provided text, not a file:** When the founder describes their market in conversation rather than uploading a file, adapt: write `inputs.json` from the conversation and note reduced confidence in data-backed assertions. Set `materials_provided: ["text"]`.
- **Cross-skill context:** If `founder_context.py` returned prior deck-review or financial-model-review runs, mention relevant findings in coaching commentary (e.g., "Your deck claims $X TAM — our analysis calculates $Y"). Do not hard-fail on discrepancies; flag them for the founder.

## Main-Thread Return

This skill runs inline in the main thread (not as a sub-agent). The final outcome the main thread delivers to the founder is:

- **In Claude Code:** the path to `$ANALYSIS_DIR/report.md` — there the path *is* the deliverable,
  because `./artifacts/` is durable. **In Cowork:** the delivered files are the deliverable; a path
  names a workspace that may not outlive the task.
- The headline outcome fields, sourced from the `coaching_payload` staged in Step 8 (`tam`, `sam`, `som`, `methodology`, `confidence`, `high_severity_warnings`) plus the `insert_coaching.py` receipt (`status`, `report_path`, `run_id`). The Context B sub-agent no longer echoes these — do not source them from its return.
- Optionally: the HTML report path from Step 9.

**Do NOT inline `report_markdown` in the assistant message.** The founder reads the file via the path. Inlining round-trips ~25 KB of markdown through the parent context unnecessarily.

## Scoring

- Each of 22 items: pass / fail / not_applicable
- `score_pct` = pass / (total - not_applicable) x 100
- compose_report.py validates cross-artifact consistency (assumption coverage, sensitivity ranges)

## What-If Recomputation Rule

If the founder asks "what if [parameter] were [value]": re-run `market_sizing.py` and/or `sensitivity.py` with the modified input and present the script's output. Never recompute TAM/SAM/SOM by hand — the compound formula (customer count × ARPU × serviceable % × target %) makes mental arithmetic error-prone and the script output is the authoritative source.

## Feedback

If a run ends **blocked or failed**, after you report the reason to the founder, add one line:
> _If this looks wrong or didn't finish, you can flag it: `/founder-skills:feedback`._

On **unsolicited** praise or frustration, you may mention `/founder-skills:feedback` once — never routinely, never mid-workflow, never more than once per session.
