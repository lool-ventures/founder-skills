---
name: ic-sim
description: "Simulates a realistic VC Investment Committee with three partner archetypes debating a startup's merits, concerns, and deal terms, scored across 28 dimensions. Run the scored simulation rather than improvising what partners would say. Also covers plain-language questions with no deck attached — 'would a VC fund us?', 'what would an investor say?', 'are we fundable?' — which run the scored simulation instead of a guess at what partners think."
when_to_use: >
  Use ONLY when the user has asked to simulate an IC discussion
  or to hear how partners would debate a specific startup, AND has
  provided enough context (a deck, a description of the company,
  or a specific fund). Do not auto-invoke on general fundraising
  questions.
  The verdict comes from three scored archetypes across 28 dimensions — run this rather than improvising what partners 'would say', which produces a plausible narrative with no scoring behind it. Verbosity is not a reason to skip it.
user-invocable: true
---

# IC Simulation Skill

Help startup founders prepare for the conversation that happens behind closed doors — the one where VC partners debate whether to invest. Produce a realistic IC simulation with three distinct partner perspectives, scored across 28 dimensions, with specific coaching on what to prepare. The tone is founder-first: a coaching tool for preparation, not a judgment.

## Skill Metadata

- **Author:** lool-ventures
- **Version:** managed in `founder-skills/.claude-plugin/plugin.json`
- **Compatibility:** Python 3.10+ and `uv` for script execution.
- **Imports (recommended):**
  - `market-sizing:sizing.json` — fund alignment and market validation
  - `deck-review:checklist.json` — deck quality assessment
- **Exports:**
  - `report.json` → `fundraise-readiness`, `dd-readiness`

## Skill Execution Model (READ FIRST)

> See `founder-skills/references/skill-execution-model.md` for the full inline-skill execution model (3 dispatch contexts, Mitigation 1+2, producer contract, Cowork quirks, per-symptom triage).

This skill runs **inline in the main thread**, not as a sub-agent — see the reference above ("Why Inline (Not Forked Sub-Agent)") for the rationale. Sub-agents are deliberately shell-free, so orchestration (producer scripts, artifact persistence) stays in the main thread.

**Two dispatch contexts for the sub-agent:**

- **Context A — Per-step analytical dispatch (Mitigation 1):** Steps 5, 6, 6b, and 8 dispatch the ic-sim agent via the `Task` tool. The novel element here is **parallel dispatch**: Step 6 (PARTNER_ANALYSIS) and Step 6b (PARTNER_REBUTTAL) each dispatch the agent **three times simultaneously** — one per partner archetype — in a **single assistant turn**. Step 5 (DETECT_CONFLICTS) and Step 8 (SCORE_DIMENSIONS) are sequential dispatches. The sub-agent does deep analysis, WRITES its output JSON to the `OUTPUT_PATH` given in its prompt (the `handoff/` dir), and returns a small receipt. The main thread gates the file with `check_handoff.py`, then pipes it through the producer script. The sub-agent never writes canonical artifacts — only its hand-off file. Step 6b is the real second debate round: each archetype sees the other two's round-1 assessments and either holds its position or moves on stated evidence; Step 7's `compose_discussion.py` then derives `discussion.json` from Steps 6 and 6b's six artifacts — never authored by the main thread.
- **Context B — Post-compose coaching dispatch:** The final step dispatches the sub-agent after `compose_report.py` writes `report.md`. The sub-agent Reads the staged `coaching_payload.json` from the hand-off dir (Mitigation 2) — it does NOT read the full `report.md` — composes the coaching commentary, WRITES it to the `OUTPUT_PATH` hand-off file, and returns a small receipt. The main thread gates the file (`check_handoff.py`) and inserts it via the shared `insert_coaching.py` script (idempotency matrix, uuid-marker replacement, run_id-parity verification — all deterministic). See the reference above for the full Context B contract.

**Tolerant JSON extraction protocol (Context B returns; also the Context A message-channel fallback):** capture the sub-agent's final assistant message. It should be raw JSON, but may be wrapped in ` ```json ... ``` ` fences or carry a prose preamble. Extract tolerantly:

1. If the message is wrapped in a ` ```json ... ``` ` (or plain ` ``` ... ``` `) fence, strip the fence first.
2. Try to parse the stripped text directly as JSON.
3. If that fails, walk through the text looking for the first `{` character and try `json.JSONDecoder().raw_decode(text[i:])` — this is brace-aware and handles nested objects correctly (unlike regex, which truncates on the first `}`).
4. If extraction fails entirely, re-prompt the sub-agent with: "Your previous reply could not be parsed as JSON. Return ONLY the JSON object — no markdown fences, no prose preamble."

Context A **receipts** don't need this protocol by hand — `check_handoff.py --receipt-json -` applies the same tolerant extraction internally; pass the final message verbatim.

## Input Formats

Accept any combination: pitch deck, financial model, data room contents, text descriptions, prior market-sizing or deck-review artifacts, or just a verbal description of the business.

## Available Scripts

All scripts are at `${CLAUDE_PLUGIN_ROOT}/skills/ic-sim/scripts/`:

- **`fund_profile.py`** — Validates fund profile structure (archetypes, check size, thesis, portfolio)
- **`detect_conflicts.py`** — Validates conflict assessments and computes summary stats
- **`compose_discussion.py`** — Derives `discussion.json` from the 3 round-1 assessments + 3 round-2 rebuttals (majority-vote consensus, debate sections from partners' own responses); rejects (exit 1, no file written) on a structurally invalid rebuttal round
- **`score_dimensions.py`** — Scores 28 dimensions across 7 categories with conviction-based scoring
- **`compose_report.py`** — Assembles report with cross-artifact validation; `--strict` exits 1 on high/medium warnings
- **`visualize.py`** — Generates self-contained HTML with SVG charts (not JSON)

Also available from `${CLAUDE_PLUGIN_ROOT}/scripts/` (shared):

- **`founder_context.py`** — Per-company context management (init/read/merge/validate)

Run with: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/ic-sim/scripts/<script>.py --pretty [args]`

## Available References

Read each when first needed — do NOT load all upfront. At `${CLAUDE_PLUGIN_ROOT}/skills/ic-sim/references/`:

- **`partner-archetypes.md`** — Read before Step 4 (main-thread use ONLY: mapping real partners to archetypes in fund-specific mode). The operative archetype rubric the PARTNER_ANALYSIS sub-agent needs is duplicated in `agents/ic-sim.md` — the sub-agent never reads this file (see "Context A hand-off protocol" below); this is a documented split, not an oversight.
- **`evaluation-criteria.md`** — No longer read by any workflow step. The operative 28-dimension rubric (status values, categories, stage calibration, dealbreaker thresholds, SaaS metrics) now lives in `agents/ic-sim.md`, inlined into the SCORE_DIMENSIONS sub-agent's system prompt. This file is kept as human-readable documentation only; edits to it do NOT propagate to sub-agent behavior — edit `agents/ic-sim.md` directly.
- **`ic-dynamics.md`** — Read before composing discussion.json. How real VC ICs work: formats, decisions, what kills deals
- **`artifact-schemas.md`** — Consult as needed when depositing agent-written artifacts

## Artifact Pipeline

Every simulation deposits structured JSON artifacts into a working directory. The final step assembles all artifacts into a report and validates consistency. This is not optional.

| Step | Artifact | Producer |
|------|----------|----------|
| 1 | founder context | `founder_context.py` read/init |
| 2 | `startup_profile.json` | Agent (heredoc) |
| 3 | `prior_artifacts.json` | Agent (heredoc) |
| 4 | `fund_profile.json` | Agent (heredoc) then `fund_profile.py` validates |
| 5 | `conflict_check.json` | Context A dispatch: DETECT_CONFLICTS → `detect_conflicts.py` |
| 6 | `partner_assessment_{visionary,operator,analyst}.json` | Context A dispatch: PARTNER_ANALYSIS × 3 **in parallel** |
| 6b | `partner_rebuttal_{visionary,operator,analyst}.json` | Context A dispatch: PARTNER_REBUTTAL × 3 **in parallel** |
| 7 | `discussion.json` | `compose_discussion.py` (derives from the 3 assessments + 3 rebuttals — nothing authored) |
| 8 | `score_dimensions.json` | Context A dispatch: SCORE_DIMENSIONS → `score_dimensions.py` |
| 9 | Report | `compose_report.py` (writes both `report.json` and `report.md`) |
| 10 | Coaching | Context B dispatch: POST_COMPOSE_COACHING |

**Rules:**
- Deposit each artifact before proceeding to the next step
- For agent-written artifacts, consult `references/artifact-schemas.md` for the JSON schema
- If a step is not applicable, deposit a stub: `{"skipped": true, "reason": "..."}`
- **Do NOT use `isolation: "worktree"`** for sub-agents — files written in a worktree won't appear in the main `$SIM_DIR`

Keep the founder informed with brief, plain-language updates at each step. **Narrate the founder-visible OUTCOME, never the internal step.** That is the test to apply, and it catches more than a word list can: the forbidden thing is not a syntax, it is talking about the machinery. Bad — "Gating and piping the extraction through the producer, then staging the coaching hand-off"; good — "I've checked your numbers and I'm writing up what stood out." Bad — "schema-drift warning on `coaching_payload`"; good — nothing, because the founder has no stake in it. **Never name an internal artifact, field, or token** (a payload key, a marker name, an artifact filename, a hand-off dir) even in plain prose with no backticks — a detector keyed on syntax cannot see "gated", "hand-off" or "canonical artifacts", but the founder still reads them and they still mean nothing to them. **The between-step progress lines are the primary leak vector, not the final summary.** They feel internal — you are narrating what you are about to do — but the founder reads every one of them, and this is where the leaks actually appear: *"Now gating the hand-off before piping through the checklist producer"*, *"Gate 1 passes"*, *"Running the final verification gate"*. Rewrite each pipeline transition as the founder-visible outcome: *"Checking your numbers against the 46-point review"*, *"Your inputs look consistent — moving on to unit economics"*, *"Finishing up and putting the report together"*. If a progress line would mean nothing to someone who has never seen this skill's internals, it does not belong in the channel. Also excluded, as before: file/script names, paths, `*.py`, `--flags`, `$vars`, exit codes ("Exit N", "not found"), `W_`/`E_` codes, JSON, and step/route labels ("Lane N", "Context A/B", "Phase N", "structure detection", "the grid", any `ALL_CAPS_TOKEN`). **Never surface the bare `pass`/`hard_pass`/`invest`/`more_diligence` verdict enum in a progress update either — `pass`/`hard_pass` mean the IC would DECLINE, and a founder reads a bare "pass" as approval; render the verdict in words (Decline / Invest / More Diligence) per Main-Thread Return, in every founder-facing line, not just the final headline.** After each analytical step (5, 6, 6b, 7), share a one-sentence finding before moving on. **The task tracker is founder-visible too — the same rule governs its labels.** "Gate the inputs review handoff", "Validate inputs.json", "resolve agent namespace paths", "Initialize founder context" are leaks even though each names a real step, and even when the prose around them is clean. Label each task by the founder-visible outcome — "Check your inputs", "Score against the review", "Write up what I found" — never by a file, directory, script, or pipeline stage.

## Workflow

### Step 0: Path Setup

**Every Bash tool call runs in a fresh shell — variables do not persist.** Prefix every Bash call that uses these paths with the variable block below, or substitute absolute paths directly:

```bash
SCRIPTS="${CLAUDE_PLUGIN_ROOT}/skills/ic-sim/scripts"
# In Cowork, CLAUDE_PLUGIN_ROOT substitutes to a host-side path that does not
# exist inside the session VM — self-heal by locating the plugin mount:
if [ ! -d "$SCRIPTS" ]; then
  SCRIPTS="$(find /sessions -type d -path '*/skills/ic-sim/scripts' 2>/dev/null | head -1)"
fi
if [ -z "$SCRIPTS" ] || [ ! -d "$SCRIPTS" ]; then
  SCRIPTS="$(find / -type d -path '*/skills/ic-sim/scripts' 2>/dev/null | head -1)"
fi
PLUGIN_ROOT="${SCRIPTS%/skills/*}"
REFS="$PLUGIN_ROOT/skills/ic-sim/references"
SHARED_SCRIPTS="$PLUGIN_ROOT/scripts"
# Resolve the canonical artifacts root via a SCRIPT, not inline bash (the agent paraphrases inline
# path computations → outputs/ vs outputs/artifacts/ drift across runs). Deterministic + creates it.
python3 "$SHARED_SCRIPTS/resolve_artifacts_root.py"   # prints ARTIFACTS_ROOT — use the printed path verbatim as ARTIFACTS_ROOT in every later block (a captured var dies in the next fresh shell)
```

The Step 0 block self-heals when `${CLAUDE_PLUGIN_ROOT}` doesn't resolve (Cowork). **In Cowork the `find` is normally THE path, not a last resort** — `${CLAUDE_PLUGIN_ROOT}` resolves to a HOST path that does not exist inside the VM, so a bash test against it fails by design rather than by misconfiguration. Expect to locate the anchor and derive the variables from it: `find / -path '*/skills/ic-sim/scripts/score_dimensions.py' 2>/dev/null | head -5`. Reaching this branch is normal; it is not a sign anything is wrong, and it is not worth narrating to the founder.

**Outputs mount is append-only.** Everything under the promoted outputs mount (`.../mnt/outputs/`, not just `$SIM_DIR`) is write-allowed and delete-denied by the platform: never `rm`, move away, or empty anything under it — **including files you created yourself**. Never create ad-hoc scratch anywhere under the outputs mount (no `_src/` copies, no run-state note files); scratch belongs in `$STAGING_DIR` (a `/tmp` dir, defined below). Do not "clean up" the outputs folder before delivering — extra working files there are expected and harmless.

**If `ARTIFACTS_ROOT` resolves to `$(pwd)/artifacts` but no `artifacts/` directory exists at `$(pwd)`:** Use `Glob` with pattern `**/artifacts/founder_context.json` to locate existing artifacts, and derive `ARTIFACTS_ROOT` from the result. If nothing is found, `mkdir -p "$ARTIFACTS_ROOT"` and proceed.

**There is no quick-check lane here, and that is deliberate.** The verdict is the product of three partner analyses plus 28 scored dimensions; any subset fast enough to be a "quick check" would produce a verdict from a fraction of the evidence, and there is no honest way to label that. So when the founder asks a small
conversational question, do not improvise an answer from your own reasoning under this skill's name —
an unproduced verdict is exactly the output a founder over-trusts. Instead, say up front what the
full run costs and let them choose: "Answering that properly means running the full IC simulation — it takes
several minutes and produces a scored report with the partner debate and the conflict check. I can run it now, or if you just want my read without the
scoring, say so and I'll answer outside the IC simulation." Naming the trade-off is honest; quietly
substituting the cheap version is not.

After Step 1 (when the slug is known):

```bash
SIM_DIR="$ARTIFACTS_ROOT/ic-sim-${SLUG}"
mkdir -p "$SIM_DIR"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
# Context A hand-off dir — PER RUN: sub-agents WRITE their raw output JSON here (the audit trail —
# raw sub-agent output as returned, before producer validation). Permanent by platform design
# (outputs/ mounts are write-allowed / delete-denied); nothing in it is ever a canonical artifact.
# The $RUN_ID segment is load-bearing: it prevents a stale prior-run file from silently passing
# the hand-off gate when a dispatch fails to write.
HANDOFF_DIR="$SIM_DIR/handoff/$RUN_ID"
mkdir -p "$HANDOFF_DIR"
# Sub-agents address the SAME dir by a different path (their file tools are rooted at the outputs
# mount in Cowork). Resolve the FULL agent-namespace path via the script — never hand-splice the
# printed root with a literal skill-name/slug/run-id string yourself (that string-splicing is
# exactly the non-determinism the resolver script exists to remove):
python3 "$SHARED_SCRIPTS/resolve_artifacts_root.py" --handoff-dir-agent \
  --dir-name "ic-sim-${SLUG}" --run-id "$RUN_ID"   # prints HANDOFF_AGENT verbatim
HANDOFF_AGENT="<printed value>"   # use verbatim in OUTPUT_PATH lines
# Ad-hoc scratch (NOT sub-agent hand-off) lives OUTSIDE the promoted outputs/ tree, in a temp dir
# that is safe to both create and reclaim. Use the printed path verbatim in later steps.
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ic-sim-${SLUG:-co}.staging.XXXXXX")"
```

Pass `RUN_ID` to all sub-agents. Every artifact written to `$SIM_DIR` must include `"metadata": {"run_id": "$RUN_ID"}` at the top level. `compose_report.py` checks that all artifact run IDs match — a mismatch triggers a `STALE_ARTIFACT` high-severity warning, blocking under `--strict`.

**Overwrite-in-place — do NOT delete prior artifacts under `$SIM_DIR`.** It is the promoted `outputs/`
tree in Cowork, where deleting a user-visible path is unsafe (Cowork can deny it; the parity gate flags
it). Each producer writes its artifact fresh via `-o` every run, and `RUN_ID` is minted fresh per run —
so if a prior run left an artifact a later step doesn't regenerate, `compose_report.py`'s `STALE_ARTIFACT`
check (run_ids must match) catches the mismatch. No bulk `rm` is needed or wanted.

### Step 1: Read or Create Founder Context

```bash
python3 "$SHARED_SCRIPTS/founder_context.py" read --artifacts-root "$ARTIFACTS_ROOT" --pretty
```

**Exit 0 (found):** Use the company slug and pre-filled fields. Proceed to Step 2.

**Exit 1 (not found):** Expected on a first run — do NOT mention this check or its exit status to the founder; if you narrate anything first, say only "Let me grab a few basics about the company." Use `AskUserQuestion` (NOT plain chat) to ask for company name, stage, sector, and geography. **If `AskUserQuestion` is genuinely unavailable in the host, do NOT skip the ask and do NOT assume the answer:** ask the same question in plain chat, state the options explicitly, and wait for an answer before continuing. The ban above is on asking casually WHILE the tool is available — it is not a reason to stall a host that lacks it.

**Stage is the one field with a real fixed label set — use it verbatim if asking.**
Options: `Pre-seed` / `Seed` / `Series A` / `Series B+`
→ `pre-seed | seed | series-a | series-b` (`founder_context.py`'s `VALID_STAGES` has 7 values including `series-c`/`series-d`/`later`; on a `Series B+` pick, ask a plain-text follow-up for the specific stage rather than defaulting to `series-b`). Company name, sector and geography cannot take fixed labels — shape each as an affirmative option carrying any derived value plus a stated-value fallback. Provide at least 2 options. Then create:

**Auto-pilot cross-reference — derive field-by-field, never all-or-nothing (do not stall an unattended run on a question the materials already answer):** if the founder has selected Auto-pilot (see Mode Selection below) and provided materials (a deck, financial model, data room, or a sufficiently detailed description), derive each of the four basics — company name, stage, sector, geography — that the materials state, instead of gating on `AskUserQuestion`; a true unattended run should not stop and wait on a prompt whose answer is already in hand. Treat the four **independently**: deriving three and missing one does NOT re-gate all four. Before treating a field as missing, try to **infer** it from a clear signal in the materials (noting it as inferred, not founder-stated): geography from a phone country code, office address, or currency (e.g. a `+972` number → Israel); stage from an ambiguous fundraise signal (a named round, round size, or "raising our seed" language → the matching stage value); sector from the product category and ICP. When running interactively, fall back to `AskUserQuestion` for **only** the specific field(s) with no derivable or inferable signal (stating what you already derived). Under Auto-pilot — where you cannot ask — mark any field that still has no signal as `to_confirm` and proceed rather than stalling.

`--stage` is enum-validated (hyphenated, lowercase) — one of: `pre-seed`, `seed`, `series-a`,
`series-b`, `series-c`, `series-d`, `later`. Passing a non-canonical token (e.g. `seriesa`,
`pre_seed`) is an argparse error and forces a retry — map the founder's answer (or the
deck-derived stage) to one of these 7 values before calling `init`.

`--sector-type` is an optional override (also enum-validated, hyphenated): one of `saas`,
`ai-native`, `marketplace`, `hardware`, `hardware-subscription`, `consumer-subscription`,
`usage-based`, `transactional-fintech`, `retail`. When omitted, `founder_context.py` auto-derives
it from `--sector` via a small alias table; if the sector doesn't match a known alias, the script
emits a runtime warning asking you to set `--sector-type` explicitly — pick the closest value from
the enum above rather than waiting for that warning.

**When no enum value fits (e.g. logistics, physical goods, industrials).** Do not silently pick
`ai-native` because the company mentions AI — that selects AI-native benchmarks for a business whose
economics are not AI-native, and nothing downstream flags it. Pick the value matching the **revenue
mechanics** (a logistics marketplace ⇒ `marketplace`; a freight SaaS ⇒ `saas`), state in the run that the
sector has no exact enum value and which one you substituted, and treat the resulting benchmark comparisons
as directional. If nothing matches on mechanics either, say so rather than choosing the least-wrong label
silently.

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
- **Two ways to finish, and only two:** run the full pipeline to completion, or run the full pipeline after stating its cost up front (there is no quick lane here). Both end
  with real artifacts on disk. Anything else is not a finished run.
- **If you are blocked, say BLOCKED and say why.** A missing input, a failed hand-off, an unreadable
  document — name it and stop. Do not substitute your own reasoning for the pipeline and present the
  result as its output.

Artifact existence is the proof of execution: if no canonical artifact was written, the skill did not
run, whatever the transcript says.

### Mode Selection

Ask the user (or infer from context):

1. **Interactive** — Pause between partner positions for founder input
2. **Auto-pilot** — Run all sections without pausing
3. **Fund-specific** — Research a real fund first. Combines with either mode.

### Steps 2-3: Extract Startup Profile and Import Prior Artifacts

Read the provided materials and extract the startup profile directly. Import any prior market-sizing or deck-review artifacts from `$ARTIFACTS_ROOT`. Deposit both artifacts to `$SIM_DIR`.

**Read `${CLAUDE_PLUGIN_ROOT}/skills/ic-sim/references/artifact-schemas.md` before writing artifacts** to ensure JSON schema compliance. (Use the literal `${CLAUDE_PLUGIN_ROOT}` token for a file-tool Read — it is pre-resolved to a host-readable path; do NOT read the `find /sessions`-derived `$REFS` value, which a host-native file tool cannot reach.)

**Stage-token reconciliation (do not copy Step 1's stage token verbatim):** `founder_context.py`'s
`--stage` enum is hyphenated (`pre-seed`, `seed`, `series-a`, `series-b`, `series-c`, `series-d`,
`later`), but `startup_profile.json`'s `stage` field — and the `KNOWN_STAGES` set
`compose_report.py` actually checks against — uses UNDERSCORED tokens (`pre_seed`, `seed`,
`series_a` are in calibrated scope; anything else, including `series_b`, is flagged
`STAGE_OUT_OF_SCOPE`). These are two different enum namespaces for the same concept. Convert
Step 1's hyphenated stage to the underscored form when writing `startup_profile.json`
(`pre-seed` -> `pre_seed`, `series-a` -> `series_a`, `seed` -> `seed` unchanged) — do not paste the
hyphenated value straight through, and do not add commentary/caveats inside the `stage` field
itself (an inline caveat there also trips `STAGE_OUT_OF_SCOPE` even when the underlying stage is
in scope).

Write `startup_profile.json`:
```bash
cat <<'PROFILE_EOF' > "$SIM_DIR/startup_profile.json"
{
  "company_name": "...",
  "simulation_date": "YYYY-MM-DD",
  "stage": "seed",
  "one_liner": "...",
  "sector": "...",
  "geography": "...",
  "business_model": "...",
  "funding_history": "...",
  "current_raise": "...",
  "key_metrics": "...",
  "materials_provided": ["..."],
  "metadata": {"run_id": "<RUN_ID>"}
}
PROFILE_EOF
```

Write `prior_artifacts.json` (stub if no prior artifacts):
```bash
cat <<'PRIOR_EOF' > "$SIM_DIR/prior_artifacts.json"
{"imported": [], "skipped": true, "reason": "No prior artifacts available", "metadata": {"run_id": "<RUN_ID>"}}
PRIOR_EOF
```

### Step 4: Build Fund Profile -> `fund_profile.json`

**Fund-specific mode only — read `${CLAUDE_PLUGIN_ROOT}/skills/ic-sim/references/partner-archetypes.md` now.** You need it to map a real fund's partners to the three archetype roles. **In generic mode, skip this read** — generic mode uses the three canonical archetypes (visionary, operator, analyst) verbatim and does no real-partner mapping, so the file adds nothing. (Literal token, not `$REFS` — a file-tool Read of the `find /sessions` path is denied on host-loop.)

**Generic mode:** Build a standard early-stage fund profile with the three canonical archetypes (visionary, operator, analyst). **OMIT the `portfolio` field entirely — do not fabricate holdings.** A generic fund is a synthesized/illustrative persona with no real portfolio; inventing companies here manufactures fictional conflicts against them downstream (Step 5), and those fabricated conflicts can distort the verdict. `portfolio` is optional in generic mode precisely so it can be left out. Use the example below verbatim as the shape, adapting only thesis/stage/check-size to the startup's sector — but keep `portfolio` absent.

**Fund-specific mode:** Use WebSearch to research fund thesis, portfolio, partner backgrounds, check size range, and stage preference. Map real partners to archetype roles. Include the researched `portfolio` array and a `sources` array (each source needs `url` or `title`).

**Validation constraints:** `check_size_range` must be a dict (not a string), `stage_focus` must be a non-empty array, each source must have `url` or `title`.

Generic-mode example (note: no `portfolio` key):

```bash
cat <<'FUND_EOF' | python3 "$SCRIPTS/fund_profile.py" --pretty --run-id "$RUN_ID" -o "$SIM_DIR/fund_profile.json"
{
  "fund_name": "Generic Early-Stage Fund",
  "mode": "generic",
  "thesis_areas": ["B2B SaaS", "AI-native tooling"],
  "check_size_range": {"min": 500000, "max": 3000000, "currency": "USD"},
  "stage_focus": ["pre-seed", "seed"],
  "archetypes": [
    {"role": "visionary", "name": "The Visionary", "background": "Repeat founder; pattern-matches on market timing and 10x outcomes", "focus_areas": ["market size", "timing", "founder ambition"]},
    {"role": "operator", "name": "The Operator", "background": "Former VP of Sales; scaled GTM at two startups", "focus_areas": ["go-to-market", "unit economics", "execution risk"]},
    {"role": "analyst", "name": "The Analyst", "background": "Ex-growth-equity; underwrites metrics and defensibility", "focus_areas": ["retention", "margins", "competitive moat"]}
  ]
}
FUND_EOF
```

**Accepted warnings:** Add `accepted_warnings` array with `code`, `match` (case-insensitive), and `reason`. Compose downgrades matching warnings to `"acknowledged"`.

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

**Path idiom for dispatch prompts (host-loop path gate):** `OUTPUT_PATH` is **relative to the sub-agent's
file-tool cwd** (the outputs mount) — built from the `resolve_artifacts_root.py --agent` namespace
(`$HANDOFF_AGENT`). Never hand a sub-agent an absolute `/sessions/...` path for a file-tool Read/Write —
the host-loop path gate denies it. ic-sim sub-agents perform **zero file reads** (all inputs are inlined
into the prompt; the archetype/28-dimension rubric lives in `agents/ic-sim.md`), so only `OUTPUT_PATH`
(a write) needs the agent namespace. A bundled `references/*.md` a MAIN-THREAD step reads is passed as the
literal `${CLAUDE_PLUGIN_ROOT}/skills/ic-sim/references/...` token (pre-resolved to a host-readable path);
never a `find /sessions`-discovered `$REFS` (a shell path a file tool can't read).

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
under `$SIM_DIR`). Hand-off files are not canonical artifacts: producers consume them only via the
explicit pipe, and `compose_report.py` never reads `handoff/`.

Ad-hoc scratch (NOT sub-agent hand-off) still goes to `$STAGING_DIR` in `/tmp` — see the reference
(`founder-skills/references/skill-execution-model.md`). Hard rule: never stage scratch anywhere under
the outputs mount (which includes `$SIM_DIR`), and never delete anything under it — see the
append-only rule in Step 0.

**General heredoc guardrail:** every templated heredoc in this file already uses a single-quoted
delimiter (`<<'PROFILE_EOF'`, `<<'FUND_EOF'`, etc.) — this is deliberate, not incidental. An
UNQUOTED heredoc delimiter (`<<EOF` without quotes) lets the shell perform variable/parameter
expansion inside the body, so a literal dollar amount like `$8M` silently shell-expands away (`$8`
is read as a variable reference, `M` is left dangling) before it ever reaches the file. This applies
to ad-hoc/improvised writes too, not just the provided templates: if you ever compose a heredoc that
isn't one of the templates above, always single-quote its delimiter when the body may contain a `$`.

### Step 5: Check Portfolio Conflicts -> `conflict_check.json` (Context A dispatch)

**This step branches on the fund `mode`** (from `fund_profile.json`): a **generic** fund skips the sub-agent; a **fund-specific** fund dispatches it.

#### Generic mode

A generic fund is a synthesized/illustrative persona with **no real portfolio** (Step 4 omits the `portfolio` field). There are no holdings to check, and assessing conflicts against invented companies would be circular — so **do NOT run a sub-agent**. Read the mode inline and, if generic, produce the deterministic empty ("clear") conflict check directly — all in ONE Bash call (each Bash call is a fresh shell, so never capture the mode in one call and test it in another):

```bash
if [ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("mode","fund_specific"))' "$SIM_DIR/fund_profile.json")" = "generic" ]; then
  python3 "$SCRIPTS/detect_conflicts.py" --generic-stub --run-id "$RUN_ID" -o "$SIM_DIR/conflict_check.json"
  echo "generic mode: wrote clear-stub conflict_check.json — skip to Step 6"
fi
```

If that printed the "skip to Step 6" line (generic mode), **skip the rest of Step 5** and go to Step 6. Otherwise the fund is fund-specific — continue below.

#### Fund-specific mode

**The sub-agent performs ZERO file reads.** Read the two inputs it needs in the main thread and paste their content into the dispatch prompt below — do not send it a path to Read.

```bash
cat "$SIM_DIR/fund_profile.json"
cat "$SIM_DIR/startup_profile.json"
```

The two JSON files print to stdout — copy each verbatim into the matching `FUND_PROFILE:` / `STARTUP_PROFILE:` block below. (Never capture into a shell variable: each Bash call runs in a fresh shell.)

**Dispatch the ic-sim sub-agent in Context A (DETECT_CONFLICTS).** Call the `Task` tool with `subagent_type: "founder-skills:ic-sim"` (a type-less dispatch falls back to the wildcard `general-purpose` agent).

**Dispatch prompt template:**

```
CONTEXT: DETECT_CONFLICTS
SIM_DIR: <absolute path to SIM_DIR>
OUTPUT_PATH: <HANDOFF_AGENT>/detect_conflicts_output.json
RUN_ID: <RUN_ID>

You are the ic-sim agent dispatched in Context A (DETECT_CONFLICTS). All
inputs are inlined below — you perform ZERO file reads for this dispatch.

FUND_PROFILE:
<paste fund_profile.json content printed by the previous Bash command, verbatim>

STARTUP_PROFILE:
<paste startup_profile.json content printed by the previous Bash command, verbatim>

For each company in the fund's portfolio, assess whether it conflicts with the
startup. Assess each company for: direct conflict, adjacent conflict, or
customer overlap. Use consistent names between portfolio and conflicts.

Use your Write tool to write to OUTPUT_PATH exactly the shape expected by
detect_conflicts.py (portfolio_size and conflicts array — no metadata block;
producer script adds it):
{
  "portfolio_size": <integer>,
  "conflicts": [
    {
      "company": "<portfolio company name>",
      "type": "direct|adjacent|customer_overlap",
      "severity": "blocking|manageable",
      "rationale": "<specific reason for conflict>"
    }
  ]
}

Write an empty conflicts array if no conflicts found. portfolio_size must equal
the number of companies in the fund's portfolio.
Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do NOT write any file other than OUTPUT_PATH — canonical artifacts are
producer-script-only; anything else you write bypasses schema validation and
run_id stamping.
```

**After the sub-agent returns:** gate the hand-off per the Context A hand-off protocol, then pipe:

```bash
cat "$HANDOFF_DIR/detect_conflicts_output.json" | \
  python3 "$SCRIPTS/detect_conflicts.py" --pretty --run-id "$RUN_ID" -o "$SIM_DIR/conflict_check.json"
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

### Step 6: Partner Assessments (PARTNER_ANALYSIS × 3 in parallel)

**The sub-agent performs ZERO file reads** — its archetype rubric is already in `agents/ic-sim.md` (no read needed), and the three dynamic inputs below must be inlined, not pointed at by path.

```bash
cat "$SIM_DIR/startup_profile.json"
cat "$SIM_DIR/fund_profile.json"
cat "$SIM_DIR/prior_artifacts.json"
```

The three JSON files print to stdout — copy each verbatim into the matching `STARTUP_PROFILE:` / `FUND_PROFILE:` / `PRIOR_ARTIFACTS:` block, IDENTICALLY, in each of the three dispatch prompts below (all three archetypes see the same shared context; only `archetype:` and `OUTPUT_PATH:` differ per dispatch). Never capture into a shell variable: each Bash call runs in a fresh shell.

#### Parallel dispatch recipe

Dispatch the ic-sim agent **THREE TIMES in parallel** via the Task tool — one per archetype (visionary, operator, analyst), **each with `subagent_type: "founder-skills:ic-sim"`** (a type-less dispatch falls back to the wildcard `general-purpose` agent). Use a **SINGLE assistant turn** with 3 Task tool calls (NOT three sequential turns). The Claude Code harness runs all three Task calls in parallel when they appear in the same assistant response.

**Dedup/idempotency guard — exactly one dispatch per archetype:** before sending the 3 Task calls,
verify your batch has exactly one `archetype:` value per {visionary, operator, analyst} — no
archetype dispatched twice, none skipped. (A fleet run dispatched "visionary" twice and "analyst"
zero times — 4 dispatches for 3 archetypes — burning a wasted paid round-trip.) If you discover
AFTER dispatching that an archetype was duplicated (e.g. two `partner_<archetype>_output.json`
receipts for the same archetype, or a missing one), do not re-dispatch all three: dispatch ONLY the
missing/skipped archetype(s) once each, and use the first valid receipt for any archetype that has
more than one.

Pseudocode for the dispatch (executed as 3 parallel Task tool_use blocks; `<shared inputs>` is the same STARTUP_PROFILE/FUND_PROFILE/PRIOR_ARTIFACTS block pasted into all three):

```
[
  Task(subagent_type="founder-skills:ic-sim", description="Partner analysis: visionary",
       prompt="CONTEXT: PARTNER_ANALYSIS\narchetype: visionary\nOUTPUT_PATH: <HANDOFF_AGENT>/partner_visionary_output.json\nRUN_ID: <id>\n<shared inputs>"),
  Task(subagent_type="founder-skills:ic-sim", description="Partner analysis: operator",
       prompt="CONTEXT: PARTNER_ANALYSIS\narchetype: operator\nOUTPUT_PATH: <HANDOFF_AGENT>/partner_operator_output.json\nRUN_ID: <id>\n<shared inputs>"),
  Task(subagent_type="founder-skills:ic-sim", description="Partner analysis: analyst",
       prompt="CONTEXT: PARTNER_ANALYSIS\narchetype: analyst\nOUTPUT_PATH: <HANDOFF_AGENT>/partner_analyst_output.json\nRUN_ID: <id>\n<shared inputs>"),
]
```

**Full dispatch prompt template** (used for each archetype, with `archetype:`/`OUTPUT_PATH:` changed — the three inlined blocks are IDENTICAL across all three dispatches):

```
CONTEXT: PARTNER_ANALYSIS
archetype: visionary|operator|analyst
SIM_DIR: <absolute path to SIM_DIR>
OUTPUT_PATH: <HANDOFF_AGENT>/partner_<archetype>_output.json
RUN_ID: <RUN_ID>

You are the ic-sim agent dispatched in Context A (PARTNER_ANALYSIS) for the
<archetype> archetype. Your archetype rubric is in your system prompt; you
perform ZERO file reads. Dynamic inputs are inlined below.

STARTUP_PROFILE:
<paste startup_profile.json content, verbatim>

FUND_PROFILE:
<paste fund_profile.json content, verbatim>

PRIOR_ARTIFACTS:
<paste prior_artifacts.json content, verbatim>

Embody the <archetype> perspective from your system-prompt rubric. Every
conviction point and concern must cite specific evidence from the startup
materials.

Use your Write tool to write to OUTPUT_PATH the partner assessment object (no
metadata block):
{
  "partner": "<archetype>",
  "verdict": "invest|more_diligence|pass|hard_pass",
  "rationale": "<200+ word explanation of the verdict from this archetype's perspective>",
  "conviction_points": ["<specific strength, min 2>", ...],
  "key_concerns": ["<specific concern, min 2>", ...],
  "questions_for_founders": ["<question the archetype would ask>", ...],
  "diligence_requirements": ["<what this partner needs to see before committing>", ...]
}
Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do NOT write any file other than OUTPUT_PATH — canonical artifacts are
producer-script-only; anything else you write bypasses schema validation and
run_id stamping.
```

**After all three sub-agents return:** gate EACH hand-off per the Context A hand-off protocol
(run `check_handoff.py` per file, branch on exit codes). Then promote each assessment
deterministically — the JSON flows from the hand-off file, never re-typed:

```bash
# Repeat for visionary, operator, analyst (change both occurrences of the role)
cat "$HANDOFF_DIR/partner_visionary_output.json" | python3 -c "
import json, sys
data = json.load(sys.stdin)
data['metadata'] = {'run_id': '$RUN_ID'}
with open('$SIM_DIR/partner_assessment_visionary.json', 'w') as f:
    json.dump(data, f, indent=2)
"
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

**Verify after writes:** check that `$SIM_DIR` contains all three `partner_assessment_*.json` files. If any are missing, re-run that dispatch before proceeding.

### Step 6b: Partner Rebuttals (PARTNER_REBUTTAL × 3 in parallel)

**This is the real second debate round — not a formality.** Round 1 (Step 6) ran the three
archetypes in parallel with no sight of each other, so nothing that happened in Step 6 was
actually a debate. This step is what makes it one: each partner reads the other two partners'
round-1 positions and decides, on the record, whether to hold or move. **A round that manufactures
agreement is worse than no round** — instruct every dispatch to hold its round-1 position unless a
rebuttal presents evidence it did not already have, never merely a more forceful restatement of a
position it already considered.

**The sub-agent performs ZERO file reads** — its archetype rubric and the 28-dimension id set it
needs for `dealbreakers[].dimension` are both already in `agents/ic-sim.md` (no read needed). The
three round-1 assessments must be inlined, not pointed at by path.

```bash
cat "$SIM_DIR/partner_assessment_visionary.json"
cat "$SIM_DIR/partner_assessment_operator.json"
cat "$SIM_DIR/partner_assessment_analyst.json"
```

The three JSON files print to stdout — copy each verbatim into the matching dispatch prompt below.
Every dispatch gets all three: its own archetype's assessment under `YOUR_ASSESSMENT` and the
other two under `OTHER_ASSESSMENTS`, IDENTICALLY in shape across all three dispatches (only
`archetype:`, `YOUR_ASSESSMENT:`, `OTHER_ASSESSMENTS:`, and `OUTPUT_PATH:` differ per dispatch).
Never capture into a shell variable: each Bash call runs in a fresh shell.

#### Parallel dispatch recipe

Dispatch the ic-sim agent **THREE TIMES in parallel** via the Task tool — one per archetype
(visionary, operator, analyst), **each with `subagent_type: "founder-skills:ic-sim"`** (a
type-less dispatch falls back to the wildcard `general-purpose` agent). Use a **SINGLE assistant
turn** with 3 Task tool calls (NOT three sequential turns), same as Step 6.

**Dedup/idempotency guard — exactly one dispatch per archetype:** the same guard as Step 6 applies
here — verify your batch has exactly one `archetype:` value per {visionary, operator, analyst}
before sending the 3 Task calls. If a duplicate/missing archetype is discovered after dispatching,
do not re-dispatch all three: dispatch ONLY the missing/skipped archetype(s) once each.

Pseudocode for the rebuttal dispatch (executed as 3 parallel Task tool_use blocks):

```
[
  Task(subagent_type="founder-skills:ic-sim", description="Partner rebuttal: visionary",
       prompt="CONTEXT: PARTNER_REBUTTAL\narchetype: visionary\nOUTPUT_PATH: <HANDOFF_AGENT>/partner_rebuttal_visionary_output.json\nRUN_ID: <id>\n<visionary's own assessment + the other two>"),
  Task(subagent_type="founder-skills:ic-sim", description="Partner rebuttal: operator",
       prompt="CONTEXT: PARTNER_REBUTTAL\narchetype: operator\nOUTPUT_PATH: <HANDOFF_AGENT>/partner_rebuttal_operator_output.json\nRUN_ID: <id>\n<operator's own assessment + the other two>"),
  Task(subagent_type="founder-skills:ic-sim", description="Partner rebuttal: analyst",
       prompt="CONTEXT: PARTNER_REBUTTAL\narchetype: analyst\nOUTPUT_PATH: <HANDOFF_AGENT>/partner_rebuttal_analyst_output.json\nRUN_ID: <id>\n<analyst's own assessment + the other two>"),
]
```

**Full dispatch prompt template** (used for each archetype, with `archetype:`/`YOUR_ASSESSMENT:`/
`OTHER_ASSESSMENTS:`/`OUTPUT_PATH:` changed per dispatch):

```
CONTEXT: PARTNER_REBUTTAL
archetype: visionary|operator|analyst
SIM_DIR: <absolute path to SIM_DIR>
OUTPUT_PATH: <HANDOFF_AGENT>/partner_rebuttal_<archetype>_output.json
RUN_ID: <RUN_ID>

You are the ic-sim agent dispatched in Context A (PARTNER_REBUTTAL) for the
<archetype> archetype. This is round 2 of the debate. Your archetype rubric
and the 28-dimension id set are already in your system prompt; you perform
ZERO file reads.

YOUR_ASSESSMENT (your own round-1 position):
<paste this archetype's own partner_assessment_<archetype>.json content, verbatim>

OTHER_ASSESSMENTS (the other two partners' round-1 positions):
<paste the other two archetypes' partner_assessment_*.json content, verbatim, both>

Read what the other two partners concluded. Hold your round-1 verdict UNLESS
one of them presents evidence you did not already have in YOUR_ASSESSMENT — a
more forceful argument for something you already considered is not a reason
to move. Only change your verdict when a specific piece of evidence in
another partner's assessment changes what you know, and say exactly what
that evidence is.

Use your Write tool to write to OUTPUT_PATH the rebuttal object (no metadata
block):
{
  "partner": "<archetype>",
  "revised_verdict": "invest|more_diligence|pass|hard_pass",
  "verdict_changed": <true if this differs from YOUR_ASSESSMENT's verdict, else false>,
  "changed_because": "<required and non-empty when verdict_changed is true — name the
    specific evidence in another partner's assessment that moved you; omit or leave
    empty when verdict_changed is false>",
  "responses": [
    {"to": "<the other archetype you are responding to>",
     "point": "<your response to their position — agree, disagree, or complicate it,
       with a reason>",
     "concedes": <true only if this specific response gives ground on your own
       prior position, else false>}
  ],
  "dealbreakers": [
    {"dimension": "<a real dimension id from the 28-dimension rubric already in your
       system prompt>", "reason": "<why this is fatal>",
     "evidence": "<the specific evidence — required, never empty>"}
  ],
  "diligence_requirements": ["<what you still need to see before committing, updated
    after hearing the other two partners>"]
}
Write at least one entry in "responses" for each of the other two archetypes (2
entries minimum). Write an empty "dealbreakers" array if you found none — never
invent one to seem thorough.
Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do NOT write any file other than OUTPUT_PATH — canonical artifacts are
producer-script-only; anything else you write bypasses schema validation and
run_id stamping.
```

**After all three sub-agents return:** gate EACH hand-off per the Context A hand-off protocol
(run `check_handoff.py` per file, branch on exit codes). Then promote each rebuttal
deterministically — the JSON flows from the hand-off file, never re-typed:

```bash
# Repeat for visionary, operator, analyst (change both occurrences of the role)
cat "$HANDOFF_DIR/partner_rebuttal_visionary_output.json" | python3 -c "
import json, sys
data = json.load(sys.stdin)
data['metadata'] = {'run_id': '$RUN_ID'}
with open('$SIM_DIR/partner_rebuttal_visionary.json', 'w') as f:
    json.dump(data, f, indent=2)
"
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

**Verify after writes:** check that `$SIM_DIR` contains all three `partner_rebuttal_*.json` files. If any are missing, re-run that dispatch before proceeding.

### Step 7: Compose Discussion -> `discussion.json` (producer pipe)

**REQUIRED — read `${CLAUDE_PLUGIN_ROOT}/skills/ic-sim/references/ic-dynamics.md` now.** (Literal token, not `$REFS` — a file-tool Read of the `find /sessions` path is denied on host-loop.)

`discussion.json` is now composed the same way every other producer-script artifact is: run the
script against the six files already on disk (three `partner_assessment_*.json` from Step 6, three
`partner_rebuttal_*.json` from Step 6b). Nothing here is authored by the main thread — the verdict,
the debate content, and the diligence list all come straight from what the partners wrote in Steps 6
and 6b. `compose_discussion.py` derives `consensus_verdict` as the value at least 2 of the 3
partners' `revised_verdict` agree on; a genuine 3-way split (no majority) becomes `more_diligence`
rather than an invented tiebreak.

```bash
python3 "$SCRIPTS/compose_discussion.py" --dir "$SIM_DIR" --run-id "$RUN_ID" --pretty \
  -o "$SIM_DIR/discussion.json"
```

**On exit 0:** `discussion.json` is written. Continue to Step 8.

**On a nonzero exit:** the rebuttal round was structurally invalid — read the JSON diagnostic on
stdout (`errors: [...]`, one entry per problem: a missing/duplicate archetype among the rebuttals,
an empty `changed_because` on a changed verdict, a `revised_verdict` outside the enum, or a
dealbreaker with no evidence or an unrecognized dimension id). **Repair-dispatch** the Step 6b
PARTNER_REBUTTAL sub-agent for the specific archetype the diagnostic names, quoting the diagnostic
verbatim, then re-run this command from the top (never hand-patch `discussion.json` — there is no
`-o` file to patch, since nothing is written on a rejection). Counts against Step 6b's Context A
retry budget (see the hand-off protocol above).

**Founder-facing narration — render partner verdicts in words.** If you summarize the three partners' positions to the founder (e.g. "visionary → …, operator → …, analyst → …"), render each verdict in words — `invest` → "Invest", `more_diligence` → "More Diligence", `pass`/`hard_pass` → "Decline" — NEVER the raw `pass`/`hard_pass`/`invest`/`more_diligence` enum. A founder reads a bare "pass" as approval when it means the opposite. This applies to any progress line that mentions a partner's or the mechanical verdict, not just the final headline (see the narration rule in the workflow preamble and Main-Thread Return).

### Step 8: Score Dimensions -> `score_dimensions.json` (Context A dispatch)

**The sub-agent performs ZERO file reads** — its 28-dimension rubric is already in `agents/ic-sim.md` (no read needed). The seven dynamic inputs below must be inlined, not pointed at by path. This is the largest inline of any ic-sim dispatch (7 JSON artifacts); inline the full files as-is — they are per-run analytical artifacts, not large machine-produced dumps.

`conflict_check.json` is inlined here (not omitted) because `fit_portfolio_conflict` is one of
the 28 dimensions — without the real conflict data, that dimension can only default to
`not_applicable` even when Step 5 found genuine conflicts.

`fund_profile.json` is inlined here too (not just at Step 4) because three more of the 28
dimensions — `fit_thesis_alignment`, `fit_stage_match`, `fit_value_add` — are defined against the
fund's actual thesis, stage focus, check size, and partner backgrounds. Step 4 builds a real
`fund_profile.json` in BOTH generic and fund-specific mode, so without this inline the sub-agent
would have no grounded basis for those three dimensions and would have to invent one — potentially
contradicting the profile already sitting on disk.

```bash
cat "$SIM_DIR/startup_profile.json"
cat "$SIM_DIR/fund_profile.json"
cat "$SIM_DIR/conflict_check.json"
cat "$SIM_DIR/discussion.json"
cat "$SIM_DIR/partner_assessment_visionary.json"
cat "$SIM_DIR/partner_assessment_operator.json"
cat "$SIM_DIR/partner_assessment_analyst.json"
```

The seven JSON files print to stdout — copy each verbatim into the matching block below. Never capture into a shell variable: each Bash call runs in a fresh shell.

**Dispatch the ic-sim sub-agent in Context A (SCORE_DIMENSIONS).** Call the `Task` tool with `subagent_type: "founder-skills:ic-sim"` (a type-less dispatch falls back to the wildcard `general-purpose` agent).

**Dispatch prompt template:**

```
CONTEXT: SCORE_DIMENSIONS
SIM_DIR: <absolute path to SIM_DIR>
OUTPUT_PATH: <HANDOFF_AGENT>/score_dimensions_output.json
RUN_ID: <RUN_ID>

You are the ic-sim agent dispatched in Context A (SCORE_DIMENSIONS). Your
28-dimension rubric is already in your system prompt — you perform ZERO file
reads for this dispatch. All dynamic inputs are inlined below.

STARTUP_PROFILE:
<paste startup_profile.json content printed by the earlier Bash command, verbatim>

FUND_PROFILE:
<paste fund_profile.json content printed by the earlier Bash command, verbatim>

CONFLICT_CHECK:
<paste conflict_check.json content printed by the earlier Bash command, verbatim>

DISCUSSION:
<paste discussion.json content printed by the earlier Bash command, verbatim>

PARTNER_ASSESSMENT_VISIONARY:
<paste partner_assessment_visionary.json content printed by the earlier Bash command, verbatim>

PARTNER_ASSESSMENT_OPERATOR:
<paste partner_assessment_operator.json content printed by the earlier Bash command, verbatim>

PARTNER_ASSESSMENT_ANALYST:
<paste partner_assessment_analyst.json content printed by the earlier Bash command, verbatim>

Score all 28 dimensions based on the evidence from the startup materials and
the partner assessments. Ensure scoring reflects the discussion conclusions —
if a dimension was debated as a dealbreaker, the score must reflect that.
Score fit_portfolio_conflict from CONFLICT_CHECK's actual conflicts array —
only mark it not_applicable if CONFLICT_CHECK genuinely found zero conflicts,
not because the data was unavailable.
Score fit_thesis_alignment, fit_stage_match, and fit_value_add from
FUND_PROFILE's actual thesis_areas, stage_focus, check_size_range, and
archetypes — never invent a hypothetical fund thesis; FUND_PROFILE is the
real profile Step 4 built for this run, in both generic and fund-specific mode.

Use your Write tool to write to OUTPUT_PATH the items array without summary
(producer script computes summary). Each item has this shape:
{
  "items": [
    {
      "id": "team_founder_market_fit",
      "category": "Team",
      "status": "strong_conviction|moderate_conviction|concern|dealbreaker|not_applicable|to_confirm",
      "evidence": "<specific evidence from startup materials>",
      "notes": "<optional explanation>"
    }
  ]
}

Score every one of these 28 dimensions — one item per id, no omissions, no
invented ids. The 28 dimension ids, grouped by category:
Team:
    {"id": "team_founder_market_fit"}
    {"id": "team_complementary_skills"}
    {"id": "team_execution_speed"}
    {"id": "team_coachability"}
Market:
    {"id": "market_size_credibility"}
    {"id": "market_timing"}
    {"id": "market_growth_trajectory"}
    {"id": "market_entry_barriers"}
Product:
    {"id": "product_differentiation"}
    {"id": "product_traction_evidence"}
    {"id": "product_technical_moat"}
    {"id": "product_user_love"}
Business Model:
    {"id": "biz_unit_economics"}
    {"id": "biz_pricing_power"}
    {"id": "biz_scalability"}
    {"id": "biz_gross_margins"}
Financials:
    {"id": "fin_capital_efficiency"}
    {"id": "fin_runway_plan"}
    {"id": "fin_path_to_next_round"}
    {"id": "fin_revenue_quality"}
Risk:
    {"id": "risk_single_point_failure"}
    {"id": "risk_regulatory"}
    {"id": "risk_competitive_response"}
    {"id": "risk_customer_concentration"}
Fund Fit:
    {"id": "fit_thesis_alignment"}
    {"id": "fit_portfolio_conflict"}
    {"id": "fit_stage_match"}
    {"id": "fit_value_add"}

Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do NOT write any file other than OUTPUT_PATH — canonical artifacts are
producer-script-only; anything else you write bypasses schema validation and
run_id stamping.
```

**After the sub-agent returns:** gate the hand-off per the Context A hand-off protocol, then pipe. Read `fund_profile.json`'s `mode` field first and pass it as `--fund-mode` — this is what makes a generic-mode dealbreaker non-blocking (see the Fund Profile section above): a real, named fund still gets the dealbreaker override unchanged.

```bash
cat "$HANDOFF_DIR/score_dimensions_output.json" | \
  python3 "$SCRIPTS/score_dimensions.py" --pretty --run-id "$RUN_ID" \
    --fund-mode "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("mode","fund_specific"))' "$SIM_DIR/fund_profile.json")" \
    -o "$SIM_DIR/score_dimensions.json"
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

### Step 8.5: Decline Confirmation Gate (conditional)

`score_dimensions.json` now carries the computed verdict. **This gate fires ONLY when that
computed verdict is a decline/fatal-flaw outcome** (`pass` or `hard_pass`) — skip it entirely
when the verdict is `invest` or `more_diligence`; a stop on every run is a tax the founder
shouldn't pay on a run that doesn't need one.

Read the verdict from the producer's output — **trigger from this producer data, never from your
own prose read of the discussion or partner assessments**:

```bash
python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["summary"]["verdict"])' "$SIM_DIR/score_dimensions.json"
```

If the printed value is `invest` or `more_diligence`, skip the rest of this step and go straight
to Step 9.

If it is `pass` or `hard_pass`, **STOP before composing the report** and confirm with the founder.
**Two separate steps — do not combine them** (same shape as every other two-step gate in this
fleet):

**Step A: Output a chat message** stating, in plain language and rendered in words — **never the
bare `pass`/`hard_pass` token**, per the verdict-in-words rule in the workflow preamble and
Main-Thread Return — that the scored result comes out to a Decline. Name what is driving it, read
from `score_dimensions.json`'s `summary.dealbreaker` and `summary.concern` counts, without
dumping the full report yet. Example: "Heads up — the scored result on this one comes out to a
Decline, with 2 dimensions flagged as fatal and 6 more as concerns. I can finish the full write-up
now, or if there's more context that would change the picture, share it first and I'll fold it
in."

**Step B: AFTER the chat message, call `AskUserQuestion`** with a one-sentence, plain-text
question — no markdown, no tables: `The scored result comes out to a Decline — want me to go ahead
and finish the full write-up?` Options: `Yes, finish the write-up` / `Hold off — let me add more
context first`.

**If "Yes, finish the write-up"** (or any clear affirmative): proceed to Step 9 as normal. This is
not a re-run and does not touch `score_dimensions.json` or any other artifact — the gate only
confirms delivery, it never recomputes anything.

**If "Hold off"**: do NOT run `compose_report.py` yet. Tell the founder you're pausing here — the
scored artifacts already on disk aren't going anywhere (the append-only rule from Step 0 covers
them) — and that you'll finish the write-up whenever they're ready, whether that means new
materials or simply telling you to go ahead anyway. Do not proceed to Step 9, 10, 11, or 12 until
a fresh founder response resumes the gate.

**What this gate is NOT.** It does not replace, weaken, or duplicate the CONSENSUS_SCORE_MISMATCH
disposition rule in Step 9 below — that rule governs how a qualitative/quantitative *mismatch* is
presented once the report exists and is unchanged: present the mechanical verdict, note the
divergence, never re-run to force agreement. This gate is upstream of that: it decides whether the
report gets composed and shown at all when the mechanical verdict itself is already a decline. The
two rules are independent and both stay in force.

### Step 9: Compose and Validate Report

```bash
python3 "$SCRIPTS/compose_report.py" --dir "$SIM_DIR" --pretty \
  -o "$SIM_DIR/report.json" \
  --write-md "$SIM_DIR/report.md"
```

`compose_report.py` writes both `report.json` and `report.md` deterministically. **Do NOT** read `report_markdown` out of `report.json` and re-write it via heredoc — agent heredoc handling can drift and produce unparseable output.

Fix high-severity warnings and re-run. Use `--strict` to enforce a clean report.

**CONSENSUS_SCORE_MISMATCH disposition rule (medium warning, no re-run needed):** when the IC
discussion's `consensus_verdict` differs from `score_dimensions.json`'s mechanical `verdict`, the
mechanical score is authoritative for the headline verdict — do NOT re-run anything or try to make
the two agree. Present the mechanical verdict as the headline — **rendered in words per Main-Thread
Return (Decline / Invest / More Diligence), never the bare `pass`/`hard_pass` enum** — and keep the
mismatch as a noted caveat (the report already renders this as an executive-summary note); mention in your own summary
that qualitative debate and the quantitative score diverged, without treating it as an error to fix.

**Post-write verification:** `compose_report.py` exits non-zero (code 2) if the declared output files don't exist or are empty after writing. If compose exits non-zero, stop and report the exact stderr — do not proceed to Step 10.

### Step 10: Post-Compose Coaching Commentary (Context B dispatch — POST_COMPOSE_COACHING)

**Dispatch the ic-sim sub-agent in Context B.** Call the `Task` tool with `subagent_type: "founder-skills:ic-sim"` after `compose_report.py` has successfully written both `report.json` and `report.md`.

**Mitigation 2 protocol:** the main thread reads the structured `coaching_payload` from `report.json` and STAGES it as a file in the hand-off dir; the sub-agent Reads it from the agent namespace (a functionally required read, so a wrong prefix fails loudly before anything is written). The sub-agent does NOT Read full `report.md` — it consumes the staged `coaching_payload.json` directly, composes the coaching commentary, and **WRITES it as plain markdown to the `OUTPUT_PATH` hand-off file (a `.md` file) with its Write tool — no JSON, no escaping — returning only a small receipt** (the same file transport as Context A — the commentary leaves the model exactly once, into the Write call; the main thread never re-types it). The main thread gates that file with `check_handoff.py --format=markdown`, transforms it into the JSON transport envelope with `md_to_commentary.py` (deterministic escaping — `json.dumps` cannot emit malformed JSON), then pipes it into the shared `insert_coaching.py` script (idempotency matrix, uuid-marker replacement, run_id-parity verification — all deterministic, unchanged). See the ic-sim agent body's "Context B — Post-compose coaching dispatch (POST_COMPOSE_COACHING)" section for the full procedure.

<!-- skill-quality-ci: bash-after-subagent-ok -->
```bash
python3 -c '
import json, sys
data = json.load(open(sys.argv[1]))
json.dump(data["coaching_payload"], open(sys.argv[2], "w"), indent=2)
print(json.dumps({"staged": sys.argv[2]}))
' "$SIM_DIR/report.json" "$HANDOFF_DIR/coaching_payload.json"
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

You are dispatched to add coaching commentary to an IC simulation report.

The compose_report.py script has finished. The structured `coaching_payload` has
been STAGED AS A FILE for you — it is not inlined in this prompt.

Read the coaching payload at <HANDOFF_AGENT>/coaching_payload.json.

If that Read FAILS, write NO file and return exactly:
{"status": "blocked", "reason": "handoff_path_unresolvable", "attempted": "<the path you tried>"}
Do not Glob for it, do not guess a different prefix, do not proceed from memory —
a failed Read here means the hand-off prefix is wrong and the main thread must
re-issue the dispatch. Reporting it is the correct outcome.

Follow your agent body's Context B procedure (POST_COMPOSE_COACHING):

1. Compose commentary from the STAGED coaching_payload (dealbreakers,
   concerns, summary, high_severity_warnings, company_name).
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
# Re-derive the shared-scripts path (fresh shell — Step 0's vars don't survive here). In Cowork
# ${CLAUDE_PLUGIN_ROOT} is a host path absent inside the session VM shell, so locate the plugin mount.
SHARED_SCRIPTS="${CLAUDE_PLUGIN_ROOT}/scripts"
if [ ! -d "$SHARED_SCRIPTS" ]; then
  IS_SCRIPTS="$(find /sessions -type d -path '*/skills/ic-sim/scripts' 2>/dev/null | head -1)"
  [ -n "$IS_SCRIPTS" ] || IS_SCRIPTS="$(find / -type d -path '*/skills/ic-sim/scripts' 2>/dev/null | head -1)"
  SHARED_SCRIPTS="${IS_SCRIPTS%/skills/*}/scripts"
fi
printf '%s' '<agent final message verbatim>' | \
  python3 "$SHARED_SCRIPTS/check_handoff.py" "$HANDOFF_DIR/coaching.md" \
    --format=markdown --agent-path "$HANDOFF_AGENT/coaching.md" --receipt-json - \
    --marker '<EXACT insertion_marker string from report.json coaching_payload>'
```

**On gate exit 0**, transform the gated hand-off FILE into the JSON transport envelope and insert (feed the file, never re-type the message):

<!-- skill-quality-ci: bash-after-subagent-ok -->
```bash
SHARED_SCRIPTS="${CLAUDE_PLUGIN_ROOT}/scripts"
if [ ! -d "$SHARED_SCRIPTS" ]; then
  IS_SCRIPTS="$(find /sessions -type d -path '*/skills/ic-sim/scripts' 2>/dev/null | head -1)"
  [ -n "$IS_SCRIPTS" ] || IS_SCRIPTS="$(find / -type d -path '*/skills/ic-sim/scripts' 2>/dev/null | head -1)"
  SHARED_SCRIPTS="${IS_SCRIPTS%/skills/*}/scripts"
fi
python3 "$SHARED_SCRIPTS/md_to_commentary.py" "$HANDOFF_DIR/coaching.md" | \
  python3 "$SHARED_SCRIPTS/insert_coaching.py" \
    --report "$SIM_DIR/report.md" \
    --marker '<EXACT insertion_marker string from report.json coaching_payload>' \
    --verify-artifact "$SIM_DIR/fund_profile.json" \
    --verify-artifact "$SIM_DIR/conflict_check.json" \
    --verify-artifact "$SIM_DIR/discussion.json" \
    --verify-artifact "$SIM_DIR/score_dimensions.json"
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

### Step 11 (Optional): Generate Visual Report

```bash
python3 "$SCRIPTS/visualize.py" --dir "$SIM_DIR" -o "$SIM_DIR/report.html"
```

**Do not hand this over here** — the Deliver step below is the only place work reaches the founder, and it sends the complete set as files. A path presented here is the partial-delivery bug.

### Step 12: Deliver Artifacts

Copy final deliverables to the **workspace root — `$ARTIFACTS_ROOT/..`, i.e. the promoted outputs mount itself, NOT `$ARTIFACTS_ROOT` and NOT `$REVIEW_DIR`**: `{Company}_IC_Simulation.md`, `.html` (if generated), `.json` (optional). Concretely, if `$ARTIFACTS_ROOT` is `<mount>/artifacts` then these go to `<mount>/`. That is the level the founder sees as deliverable cards; `artifacts/` below it is working state. Do not infer the level by elimination — `dirname "$ARTIFACTS_ROOT"` is the answer.

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
anything under `$SIM_DIR`** — it is the promoted `outputs/` tree in Cowork, where deleting a
user-visible path is unsafe (and the parity gate flags it).

## Main-Thread Return

This skill runs inline in the main thread (not as a sub-agent). The final outcome the main thread delivers to the founder is:

- **In Claude Code:** the path to `$SIM_DIR/report.md` — there the path *is* the deliverable, because
  `./artifacts/` is durable. **In Cowork:** the delivered files are the deliverable; a path
  names a workspace that may not outlive the task.
- The headline outcome fields, sourced from the `coaching_payload` staged in Step 10 (`decision` = `summary.verdict`, `consensus_strength`, `key_concerns` from `concerns[].dimension`, `high_severity_warnings`) plus the `insert_coaching.py` receipt (`status`, `report_path`, `run_id`). The Context B sub-agent no longer echoes these — do not source them from its return.

  **Nesting matters here, and it is mixed — read the path, not the pattern:** only `verdict` sits under `coaching_payload.summary` (alongside `conviction_score` and the four conviction counts). The other three named fields are **top level** on `coaching_payload`: `consensus_strength`, `concerns`, `high_severity_warnings`. Reaching under `summary` for those returns null. IC simulation has no checklist artifact and no `score_pct` — its scoring output is `score_dimensions.json`.
- Optionally: the HTML report path from Step 11.

**Do NOT inline `report_markdown` in the assistant message.** The founder reads the file via the path.

**Headline the verdict in words, NEVER the raw enum.** `decision` (= `summary.verdict`) is an internal token: `pass`/`hard_pass` mean the IC would **DECLINE**; a founder reads a bare "Pass" as "passed the bar" — the opposite. When you state the outcome in your chat message, lead with the SAME rendering `compose_report.py` writes into the report — never surface the bare `pass`/`hard_pass`/`invest`/`more_diligence` token:
- `invest` → "Invest — strong enough for a term sheet discussion"
- `more_diligence` → depends on WHY, and the reason changes the words. Check
  `summary.coverage_floored` / `summary.coverage_capped` **before** you write the headline:
  - neither set (earned on the merits) → "More Diligence — promising but needs more evidence"
  - `coverage_held` → "More Diligence — too little disclosed to reach a verdict". Same wording as
    `coverage_floored`: nothing moved the verdict, but coverage was too thin for "promising" to describe
    anything that was actually assessed. **This is the case that used to slip through** — the verdict lands
    in the band on its own, so neither the cap nor the floor fires, and the merits wording appeared on a
    scorecard where almost nothing was scoreable.
  - `coverage_floored` → "More Diligence — too little disclosed to reach a verdict (not a negative
    signal)". Do NOT say "promising": nothing was assessed, so nothing has been found promising.
  - `coverage_capped` → "More Diligence — the confirmed dimensions score well, but too much is
    undisclosed to underwrite"
- `pass` → "Decline — too many concerns to proceed at this time"

**Never quote the conviction score bare when `summary.conviction_basis.sufficient` is false.** A
percentage off two applicable dimensions ("50.0%") reads as a considered midpoint across the whole
framework — the decimal place implies evidence that does not exist. State it with its denominator
("50% — but scored on only 2 of 28 dimensions") and point the founder at the breakdown rather than the
headline. `compose_report.py` already renders it that way in the report; match it in chat.
- `hard_pass` → "Decline — Hard Pass: fatal flaw identified"

**When the verdict was held by coverage, say so — do not let it read as a judgement.** If
`summary.coverage_floored` is true, the low conviction reflects **missing information, not assessed
weakness**, and the verdict was raised off a decline. Tell the founder that explicitly: the review
could not reach a verdict because N dimensions were undisclosed, and name what to supply. Presenting
that as "promising but needs more evidence" overstates it; presenting it as a decline is worse. If
`summary.coverage_capped` is true, the mirror applies — conviction sits in the invest band but too
much is unconfirmed to say so.

## Scoring

- 28 dimensions, each: `strong_conviction` / `moderate_conviction` / `concern` / `dealbreaker` / `not_applicable` / `to_confirm`
- Scoring on fewer than 8 of the 28 dimensions raises a thin-base flag: the score stands, but it must be presented with its denominator.
- `to_confirm` = data the materials don't disclose (excluded from `applicable`, like `not_applicable`); >6 of them holds the verdict at `more_diligence` in BOTH directions — capped down from `invest` (thin coverage can't earn conviction) and floored up from `pass` (you cannot decline a company on the grounds that you weren't told anything). Absence-as-weakness is `concern`, not `to_confirm`.
- Conviction score: `(strong*1.0 + moderate*0.5) / applicable * 100`
- Verdicts: `invest` (>=75%), `more_diligence` (>=50%), `pass` (<50%), `hard_pass` (any dealbreaker)
- One dealbreaker forces `hard_pass` regardless of score

## What-If Recomputation Rule

If the founder asks "what if [dimension] changed to [status]": re-run `score_dimensions.py` with the updated item statuses and present the script's output. Never recompute the conviction score by hand — the formula (strong×1.0 + moderate×0.5) ÷ applicable × 100 interacts with dealbreaker override logic in non-obvious ways, and the script is the authoritative source.

## Cross-Agent Integration

This skill imports artifacts from prior market-sizing and deck-review analyses. Imported artifacts are recorded with dates. Imports older than 7 days are flagged as `STALE_IMPORT`.

## Feedback

If a run ends **blocked or failed**, after you report the reason to the founder, add one line:
> _If this looks wrong or didn't finish, you can flag it: `/founder-skills:feedback`._

On **unsolicited** praise or frustration, you may mention `/founder-skills:feedback` once — never routinely, never mid-workflow, never more than once per session.
