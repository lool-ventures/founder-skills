---
name: financial-model-review
description: "Reviews startup financial models for investor readiness: validates unit economics, stress-tests runway scenarios, and benchmarks metrics against stage-appropriate targets. Use the full review, about 10–15 minutes, when the user provides a financial model (Excel, CSV, or a model pasted as text) and asks for review, validation, runway analysis, or unit-economics scoring. For a single money question with figures to compute, such as 'how long do I have?' or 'is a 4x burn multiple bad?', use its shorter quick check, so the answer comes from the calculator and dated benchmarks, not mental arithmetic."
when_to_use: >
  Do not start on general questions about financial models or fundraising that
  have no figure to compute. Verbosity is not a reason to skip it.
user-invocable: true
---

# Financial Model Review Skill

Help startup founders understand how investors will evaluate their financial model — validating structure, unit economics, runway, and metrics against stage-appropriate standards. Produce a thorough review with actionable improvements. The tone is founder-first: a rigorous but supportive coaching session.

## Skill Execution Model (READ FIRST)

> See `founder-skills/references/skill-execution-model.md` for the full inline-skill execution model (3 dispatch contexts, Mitigation 1+2, producer contract, Cowork quirks, per-symptom triage).

This skill runs **inline in the main thread**, not as a sub-agent — see the reference above ("Why Inline (Not Forked Sub-Agent)") for the rationale. Sub-agents are deliberately shell-free, so orchestration (producer scripts, artifact persistence) stays in the main thread.

**Two dispatch contexts for the sub-agent:**

- **Context A — Per-step analytical dispatch (Mitigation 1):** The INPUTS_REVIEW and CHECKLIST steps dispatch the financial-model-review agent via the `Task` tool. The agent does deep analysis, WRITES its output JSON to the `OUTPUT_PATH` given in its prompt (the `handoff/` dir), and returns a small receipt. The main thread gates the file with `check_handoff.py`, then pipes it through the producer script. The sub-agent never writes canonical artifacts — only its hand-off file. (Unit economics and runway are NOT dispatched — those producers consume `inputs.json` verbatim, so the main thread pipes the file directly.)
- **Context B — Post-compose coaching dispatch:** The final step dispatches the sub-agent after `compose_report.py` writes `report.md`. The sub-agent Reads the staged `coaching_payload.json` from the hand-off dir (Mitigation 2) — it does NOT read the full `report.md` — composes the coaching commentary, WRITES it to the `OUTPUT_PATH` hand-off file, and returns a small receipt. The main thread gates the file (`check_handoff.py`) and inserts it via the shared `insert_coaching.py` script (idempotency matrix, uuid-marker replacement, run_id-parity verification — all deterministic). See the reference above for the full Context B contract.

**Tolerant JSON extraction protocol (Context B returns; also the Context A message-channel fallback):** capture the sub-agent's final assistant message. It should be raw JSON, but may be wrapped in ` ```json ... ``` ` fences or carry a prose preamble. Extract tolerantly:

1. If the message is wrapped in a ` ```json ... ``` ` (or plain ` ``` ... ``` `) fence, strip the fence first.
2. Try to parse the stripped text directly as JSON.
3. If that fails, walk through the text looking for the first `{` character and try `json.JSONDecoder().raw_decode(text[i:])` — this is brace-aware and handles nested objects correctly (unlike regex, which truncates on the first `}`).
4. If extraction fails entirely, re-prompt the sub-agent with: "Your previous reply could not be parsed as JSON. Return ONLY the JSON object — no markdown fences, no prose preamble."

Context A **receipts** don't need this protocol by hand — `check_handoff.py --receipt-json -` applies the same tolerant extraction internally; pass the final message verbatim.

**If a sub-agent wrote CANONICAL artifact files directly anyway** (anything outside its `handoff/` OUTPUT_PATH): do not trust them — take its gated hand-off file (or extract the JSON from its final message on the fallback path), then re-pipe through the producer script as specified; the producer overwrites the file with the validated, run_id-stamped version. For INPUTS_REVIEW specifically: if `inputs.json` contains the `{"corrected": ..., "corrections": ...}` wrapper, the sub-agent wrote its reply to disk — feed that wrapper through `apply_corrections.py` as usual.

**Context-pressure note:** The win from Mitigation 1 is excluding sub-agent reasoning and the raw `extract_model.py` output (which can run to megabytes on real models) — which flows *through* the INPUTS_REVIEW dispatch: the sub-agent reads it in its own context window, returns only the corrected `inputs.json`. The artifacts themselves still accumulate in the main thread (~80-130K total), but that is manageable.

## Input Formats

Accept any format: Excel (.xlsx), CSV, Google Sheets exports, financial documents, or conversational input. For Excel files, use `extract_model.py` to parse. For other formats, extract data manually into the `inputs.json` schema. If multiple copies of the same file exist (e.g., `Financials.xlsx` and `Financials (1).xlsx`), use the most recently modified version and note the duplication to the founder. If timestamps are identical, ask the founder which file to use. If the founder cannot be queried, prefer the file without parenthetical suffixes (e.g., `(1)`, `(2)`) — these typically indicate browser re-download duplicates.

Shared references, read as needed from `${CLAUDE_PLUGIN_ROOT}/references/` (shared): `stage-expectations.md`, `benchmarks.md`, `israel-guidance.md`, `revenue-model-types.md`, `common-mistakes.md`

## Artifact Pipeline

Every review deposits structured JSON artifacts into a working directory. The final step assembles all artifacts into a report and validates consistency. This is not optional.

| Step | Artifact | Producer |
|------|----------|----------|
| 1 | founder context | `founder_context.py` read/init |
| 2 | `model_data.json` | `extract_model.py` (Excel/CSV in main thread) |
| 3 | `inputs.json` | Context A dispatch: INPUTS_REVIEW → `apply_corrections.py` |
| 3.5 | `corrected_inputs.json` | `apply_corrections.py` (from INPUTS_REVIEW dispatch) |
| 3.6 | `extraction_validation.json` | `validate_extraction.py` (when `model_data.json` exists) |
| 4 | `unit_economics.json` | direct pipe: `inputs.json` → `unit_economics.py` |
| 4 | `runway.json` | direct pipe: `inputs.json` → `runway.py` |
| 5 | `checklist.json` | Context A dispatch: CHECKLIST → `checklist.py` (grades against the two above) |
| 7 | Report | `compose_report.py` (writes both `report.json` and `report.md`) |
| 7.5 | `commentary.json` | agent-authored (main thread heredoc) — required by Gate 2 for quantitative reviews |
| 8a | HTML report | `visualize.py` |
| 8b | Explorer | `explore.py` |
| 8c | Coaching | Context B dispatch: POST_COMPOSE_COACHING |

**Rules:**
- Deposit each artifact before proceeding to the next step
- For agent-written artifacts (inputs.json), consult `${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/references/schema-inputs.md` for the JSON schema
- If a step is not applicable, deposit a stub: `{"skipped": true, "reason": "..."}`
- **Do NOT use `isolation: "worktree"`** for sub-agents — files written in a worktree won't appear in the main `$REVIEW_DIR`

Keep the founder informed with brief, plain-language updates at each step. **Narrate the founder-visible OUTCOME, never the internal step.** That is the test to apply, and it catches more than a word list can: the forbidden thing is not a syntax, it is talking about the machinery. Bad — "Gating and piping the extraction through the producer, then staging the coaching hand-off"; good — "I've checked your numbers and I'm writing up what stood out." Bad — "schema-drift warning on `coaching_payload`"; good — nothing, because the founder has no stake in it. **Never name an internal artifact, field, or token** (a payload key, a marker name, an artifact filename, a hand-off dir) even in plain prose with no backticks — a detector keyed on syntax cannot see "gated", "hand-off" or "canonical artifacts", but the founder still reads them and they still mean nothing to them. **The between-step progress lines are the primary leak vector, not the final summary.** They feel internal — you are narrating what you are about to do — but the founder reads every one of them, and this is where the leaks actually appear: *"Now gating the hand-off before piping through the checklist producer"*, *"Gate 1 passes"*, *"Running the final verification gate"*. Rewrite each pipeline transition as the founder-visible outcome: *"Checking your numbers against the 46-point review"*, *"Your inputs look consistent — moving on to unit economics"*, *"Finishing up and putting the report together"*. If a progress line would mean nothing to someone who has never seen this skill's internals, it does not belong in the channel. Also excluded, as before: file/script names, paths, `*.py`, `--flags`, `$vars`, exit codes ("Exit N", "not found"), `W_`/`E_` codes, JSON, and step/route labels ("Lane N", "Context A/B", "Phase N", "structure detection", "the grid", any `ALL_CAPS_TOKEN`). After each analytical step (3–5), share a one-sentence finding before moving on. Track progress with at most one batched task tracker (a single `TaskCreate`), updating it only at phase boundaries — extraction, review gate, scoring, report — never per sub-step: the step narration above is the founder's progress channel, so per-substep `TaskCreate`/update churn only adds runtime. **The task tracker is founder-visible too — the same rule governs its labels.** "Gate the inputs review handoff", "Validate inputs.json", "resolve agent namespace paths", "Initialize founder context" are leaks even though each names a real step, and even when the prose around them is clean. Label each task by the founder-visible outcome — "Check your inputs", "Score against the review", "Write up what I found" — never by a file, directory, script, or pipeline stage.

## Workflow

### Step 0: Path Setup

**Every Bash tool call runs in a fresh shell — variables do not persist.** Run the block below exactly **once**: it resolves `$PLUGIN_ROOT` deterministically, and every later block must substitute the printed value as a literal rather than re-running the resolution — repeating the self-heal search can land on a different mount than Step 0 picked when more than one is present (see why in the block's comments).

Optional, best-effort, and via the **Read tool** (not a shell command): before the block below, Read `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json` and note its `version` field as `EXPECT_VERSION`. Passing it to `select_plugin_root.py` below lets an exact version match win over an arbitrary first hit. If the Read fails, skip it and omit `--expect-version` — selection is still deterministic without it. Skip it if that path still begins with `$`.

Run the block below with `${CLAUDE_PLUGIN_ROOT}` exactly as it appears.

```bash
IFS= read -r TEXT_ROOT_RAW <<'EOF'
${CLAUDE_PLUGIN_ROOT}
EOF
SCRIPTS="${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/scripts"
case "$TEXT_ROOT_RAW" in *'$'*|'') SCRIPTS="" ;; esac   # text arrived unfilled: ignore any exported value
if [ ! -d "$SCRIPTS" ]; then
  # In Cowork, CLAUDE_PLUGIN_ROOT substitutes to a host-side path absent inside
  # the session VM — self-heal by collecting EVERY candidate mount (a session can
  # have more than one at once: a stale host-side cache, a test marketplace, even
  # a symlink into a different session's tree) and handing them to
  # select_plugin_root.py, which picks ONE deterministically and names the
  # rejects — never trust `find`'s arbitrary first hit, which can silently mix
  # scripts across plugin versions mid-pipeline.
  ours() { python3 -c 'import json, sys
for c in sys.stdin.read().splitlines():
    try: n = json.load(open(c.rsplit("/skills/", 1)[0] + "/.claude-plugin/plugin.json"))["name"]
    except Exception: n = "founder-skills"
    if n == "founder-skills": print(c)'; }
  CANDIDATES="$(find /sessions -type d -path '*/skills/financial-model-review/scripts' 2>/dev/null | ours)"
  [ -n "$CANDIDATES" ] || CANDIDATES="$(find /root/.claude/plugins -type d -path '*/skills/financial-model-review/scripts' 2>/dev/null | ours)"
  [ -n "$CANDIDATES" ] || CANDIDATES="$(find / -type d -path '*/skills/financial-model-review/scripts' 2>/dev/null | ours)"
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
  SCRIPTS="$PLUGIN_ROOT/skills/financial-model-review/scripts"
fi
PLUGIN_ROOT="${SCRIPTS%/skills/*}"
echo "PLUGIN_ROOT=$PLUGIN_ROOT"   # resolved ONCE, here — paste this literal into every later block; never re-run this resolution. PLUGIN_ROOT is the shell's path: never Read from it or put it in a sub-agent prompt. Exception: a READ_ROOT= printed below goes in Reads and prompts.
SHARED_SCRIPTS="$PLUGIN_ROOT/scripts"
# PREFLIGHT: the run STOPS if this prints (the skill was served without its plugin). Test for
# check_handoff.py, never a /mnt/skills path: a working first-message session shows that path too.
[ -f "$SHARED_SCRIPTS/check_handoff.py" ] || echo "UNSUPPORTED_ENVIRONMENT: the plugin's shared scripts are not reachable from here"
[ -f "$SHARED_SCRIPTS/check_handoff.py" ] && case "$TEXT_ROOT_RAW" in
  *'$'*|'') echo "PATH_STATE=literal"; echo "READ_ROOT=$PLUGIN_ROOT" ;;
  /sessions/*) echo "PATH_STATE=local" ;;
  *) if [ -d "$TEXT_ROOT_RAW" ]; then echo "PATH_STATE=substituted"; else echo "PATH_STATE=local"; fi ;;
esac
# Resolve the canonical artifacts root via a SCRIPT, not inline bash (the agent paraphrases inline
# path computations → outputs/ vs outputs/artifacts/ drift across runs). Deterministic + creates it.
python3 "$SHARED_SCRIPTS/resolve_artifacts_root.py"   # prints ARTIFACTS_ROOT — use the printed path verbatim as ARTIFACTS_ROOT in every later block (a captured var dies in the next fresh shell)
```

**If the preflight line printed `UNSUPPORTED_ENVIRONMENT`, stop here.** This environment serves the
skill without the rest of its plugin: the shared scripts are missing and sub-agents cannot be
dispatched, so the gates, the hand-off checks and the independent review steps below cannot run.
Tell the founder, in one sentence, that this skill needs Claude Cowork or Claude Code and that you
have not run it — then stop. Do not improvise the missing steps: an analysis that grades itself and
reviews itself reads exactly like one that was checked, which is the failure this stop exists to
prevent.

**Then start the run's record, once**, with every request line that starts `FS_HOST_` copied between the markers (none: leave the placeholder, which is ignored). `RUN_ID` is the `run_id` it prints. Any non-zero exit here or from `bind` below: say in one sentence that the review could not start, and stop.

```bash
python3 "<printed PLUGIN_ROOT>/scripts/run_status.py" start --skill financial-model-review --artifacts-root "<printed ARTIFACTS_ROOT>" <<'FS_HOST_EOF'
<each FS_HOST_ line of the request>
FS_HOST_EOF
```

Plugin folder for Reads and prompts (as loaded): `${CLAUDE_PLUGIN_ROOT}` — this skill's references are in `${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/references/`. If Step 0 printed `READ_ROOT=`, use that value instead.

**Plugin paths.** If Step 0 printed `READ_ROOT=`, this skill's text arrived without its plugin folder filled in. Use that value in place of `${CLAUDE_PLUGIN_ROOT}` in every Read and sub-agent prompt, including where a later step says to leave that path literal. If it did not print `READ_ROOT=`, use the paths as shown. The folder comes from Step 0's filesystem search, not from a skill file or the "Base directory" line, which can name a folder that does not exist. These are setup details: updates to the founder are about their company, not file locations, printed paths or plugin versions.

**Outputs mount is append-only.** Everything under the promoted outputs mount (`.../mnt/outputs/`, not just `$REVIEW_DIR`) is write-allowed; by this skill's rule, not a platform limit, nothing there is deleted, since a removed file may be one the founder or a later step still needs: never `rm`, move away, or empty anything under it — **including files you created yourself**. Never create ad-hoc scratch anywhere under the outputs mount (no `_src/` copies, no run-state note files); scratch belongs in `$STAGING_DIR` (a `/tmp` dir, defined below). Do not "clean up" the outputs folder before delivering — extra working files there are expected and harmless. The uploaded document is already readable in place from the uploads mount; never copy it under outputs to make it readable.

**If `ARTIFACTS_ROOT` resolves to `$(pwd)/artifacts` but no `artifacts/` directory exists at `$(pwd)`:** The workspace may not be mounted yet. Use `Glob` with `path` set to the printed `ARTIFACTS_ROOT` and pattern `founder-context-*.json` to find earlier artifacts (always pass `path`: on a cloud session the working folder is the home directory). If nothing is found, `mkdir -p "$ARTIFACTS_ROOT"` and proceed — never a relative `./artifacts`, which resolves against the shell's cwd (the session root) and lands outside the outputs mount, undelivered.

After Step 1 (when the slug is known), derive `REVIEW_DIR`. **Two modes** — pick exactly one:

- **Full review** (default — the founder attached a model, asked for a review, a report, or the
  interactive explorer, OR there is no existing full review for this slug): run Steps 2–11.
  `REVIEW_DIR="$ARTIFACTS_ROOT/financial-model-review-${SLUG}"`.
- **Quick-check mode** — a single directional question in conversation, no model attached and no
  request for a review ("with $400k in the bank and $60k/mo net burn, how long do I have?", "is a 4x
  burn multiple bad at seed?"). Run Step 5-quick instead of Steps 2–11.
  `REVIEW_DIR="$ARTIFACTS_ROOT/financial-model-review-${SLUG}-quickcheck"`.

**Tie-breaker when both bullets seem to fit.** Decide on the **verb, not the inputs**: a request for the
work product ("review my model, analyze our runway, I need this for the board") is a **full run** even when every number is already in hand, while a request for a
read ("roughly, ballpark, how long do I have, is X bad") is a **quick check** even when materials are attached. Complete inputs make the full run
faster, not less wanted. When the verb is genuinely absent, default to the **full run** and say you did —
an unwanted full run costs time, an unwanted quick check costs the founder the analysis they came for.

**Never answer from your own arithmetic.** Quick-check exists because the alternative a model reaches
for — computing runway in its head and offering the real review as an opt-in — produces a number with
no scenario stress-test, no benchmark provenance, and no record, under this skill's name. Running
fewer producers is fine; running none is not.

#### Step 5-quick: the quick-check path

Run it after the slug block below has created `REVIEW_DIR` and bound the run. Run only the producer(s) the question actually needs, with the inputs the founder gave you:

```bash
# Runway question -> runway.py alone. Unit-economics question -> unit_economics.py alone.
python3 "$SCRIPTS/runway.py" --pretty \
  --run-id "$RUN_ID" -o "$REVIEW_DIR/runway.json" <<'JSON'
{"cash": {"current_balance": <cash on hand>, "monthly_net_burn": <monthly net burn>}}
JSON
```

Then close the run's record: `python3 "$SHARED_SCRIPTS/run_status.py" finish --mode quick_check --run-id "$RUN_ID" --artifacts-root "$ARTIFACTS_ROOT" --output "$REVIEW_DIR/runway.json"` (the artifact you wrote).

That is the whole input a runway question needs: cash in the bank and net burn per month, each a plain
number (burn positive while burning), no `company` block. Add `"revenue": {"monthly_total": <monthly revenue>}` only when the
founder gave it. `unit_economics.py` still needs `company` with the stage it grades against.

**Producers deliberately NOT run:** `extract_model.py`, `validate_extraction.py`,
`validate_inputs.py`, `checklist.py`, the producer the question didn't need, `compose_report.py`,
`visualize.py`, `explore.py`, `verify_review.py`, and the Context-B coaching dispatch. No `report.md`
is written.

**Same-numbers guarantee.** The figures are identical to what the full review would compute from the
same inputs — it is the same script reading the same shape. Only the production weight is dropped.
What you do *not* get is what the skipped producers add: the anti-hallucination extraction gate, the
four-layer input validation, the 46-item checklist, multi-scenario stress-testing, and the
cross-artifact consistency checks.

**Presenting it.** Label it a quick check, not a review. Give the figure, name the inputs it came
from, and state plainly that nothing was validated or stress-tested. Then close with a **statement**,
never a question: "The full review validates the model, stress-tests runway across scenarios, and
scores 46 investor criteria — say the word and I'll run it." A question invites a "no" to something
the founder would have wanted.

```bash
REVIEW_DIR="${REVIEW_DIR:-$ARTIFACTS_ROOT/financial-model-review-${SLUG}}"              # full review
# REVIEW_DIR="${REVIEW_DIR:-$ARTIFACTS_ROOT/financial-model-review-${SLUG}-quickcheck}"  # quick check
RUN_ID="<the run_id start printed>"
mkdir -p "$REVIEW_DIR" && python3 "$SHARED_SCRIPTS/run_status.py" bind --run-id "$RUN_ID" \
  --artifacts-root "$ARTIFACTS_ROOT" --run-dir "$REVIEW_DIR" --slug "$SLUG" || exit 1
# Context A hand-off dir — PER RUN: sub-agents WRITE their raw output JSON here (the audit trail —
# raw sub-agent output as returned, before producer validation). Permanent by rule
# (nothing under outputs/ is ever deleted, by this skill's rule); nothing in it is ever a canonical artifact.
# The $RUN_ID segment is load-bearing: it prevents a stale prior-run file from silently passing
# the hand-off gate when a dispatch fails to write.
HANDOFF_DIR="$REVIEW_DIR/handoff/$RUN_ID"
mkdir -p "$HANDOFF_DIR"
# FILE-TOOL PATHS (Cowork only; skip when ARTIFACTS_ROOT does not start with /sessions/). File tools
# refuse a RELATIVE path and cannot open /sessions/... paths. FIRST, with the Write tool, write
# "<HOST_OUTPUTS>/artifacts/.host-outputs-probe" containing exactly <HOST_OUTPUTS>: the file-tool path
# your context maps to /sessions/<id>/mnt/outputs/ (the "Paths in bash differ from what file tools
# see" list; no such list -> that /sessions/.../mnt/outputs path itself). Then prove it (quoted; it may
# contain spaces). Exit 0 = proven. 2/4/5 -> fix per its JSON, retry once, then STOP:
python3 "$SHARED_SCRIPTS/resolve_artifacts_root.py" --set-host-outputs-dir "<HOST_OUTPUTS>"
# Sub-agents address the SAME dir by a different path (the absolute file-tool path
# proven above). Resolve the FULL agent-namespace paths via the script — never hand-splice the
# printed root with a literal skill-name/slug/run-id string yourself (that string-splicing is
# exactly the non-determinism the resolver script exists to remove):
python3 "$SHARED_SCRIPTS/resolve_artifacts_root.py" --handoff-dir-agent \
  --dir-name "financial-model-review-${SLUG}" --run-id "$RUN_ID"   # prints HANDOFF_AGENT verbatim
HANDOFF_AGENT="<printed value>"   # use verbatim in OUTPUT_PATH lines
# Sub-agent READ paths for under-outputs artifacts use the SAME agent namespace (absolute once proven;
# a relative or /sessions/... read is refused):
python3 "$SHARED_SCRIPTS/resolve_artifacts_root.py" --analysis-dir-agent \
  --dir-name "financial-model-review-${SLUG}"   # prints the dir in the agent namespace
REVIEW_DIR_AGENT="<printed value>"   # e.g. model_data.json, inputs.json reads
# Ad-hoc scratch (NOT sub-agent hand-off) lives OUTSIDE the promoted outputs/ tree, in a temp dir
# that is safe to both create and reclaim. Use the printed path verbatim in later steps.
# Scratch output (a redirect or a temp file) goes in $STAGING_DIR, never a fixed /tmp/<name>: /tmp is shared across sessions.
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/financial-model-review-${SLUG:-fmr}.staging.XXXXXX")"
```

**A resumed run** (`start` printed `resume: 1`) runs Step 1 and this block again, then continues at its `resume_step`; the work before it is this run's and stays.

Pass `RUN_ID` to all sub-agents. The four producer artifacts (`inputs.json`, `checklist.json`, `unit_economics.json`, `runway.json`) must carry `"metadata": {"run_id": "$RUN_ID"}` at the top level — including skipped stubs, whose stub heredoc carries the same `"metadata": {"run_id": "$RUN_ID"}` block. The producers propagate it from their stdin payloads; never hand-edit script outputs to add it. (`model_data.json` and `extraction_validation.json` have no run_id by design.) `compose_report.py` checks that all present run IDs match — a mismatch triggers a `STALE_ARTIFACT` high-severity warning, blocking under `--strict`. Stub artifacts are exempt from the value comparison but still carry the `run_id` key so the Context B parity grep finds it.

**Overwrite-in-place — do NOT delete prior artifacts under `$REVIEW_DIR`.** It is the promoted
`outputs/` tree in Cowork, where deleting a user-visible path is unsafe (our rule forbids it, and older hosts refused it; the parity
gate flags it). Each producer writes its artifact fresh via `-o` every run, and every run has its own
`RUN_ID` — so if a prior run left an artifact a later step doesn't regenerate, `compose_report.py`'s
`STALE_ARTIFACT` check (run_ids must match) catches the mismatch. No bulk `rm` is needed or wanted.

### Step 1: Read or Create Founder Context

```bash
python3 "$SHARED_SCRIPTS/founder_context.py" read --artifacts-root "$ARTIFACTS_ROOT" --run-id "$RUN_ID" \
  --skill financial-model-review --pretty
```

Three cases based on exit code:

**Exit 0 (found, single context):** Open the questions (the block below) first. Use the company slug and pre-filled fields. Before proceeding to extraction, use `AskUserQuestion` to ask the founder for current cash balance and date if not already stated in the conversation — this is the #1 cause of incomplete runway analysis. If files are attached, also ask about monthly burn rate unless the conversation already contains it. Same runtime-labelled shape as the cash/date/burn questions below (an affirmative carrying any already-stated value, plus a "Not stated" fallback) — these are dollar amounts and dates, not a fixed label set. Batch all questions into a **single `AskUserQuestion` call**.

**Exit 1 (not found: no `code`, or `CONTEXT_NOT_FOUND`):** Open the questions (the block below) first. Use `AskUserQuestion` (NOT plain chat) to ask the founder for company details AND key financial context. **You MUST use the `AskUserQuestion` tool** — do not just list questions in the chat. Gather everything in a **single call** (one interaction = one chance for the UI to render correctly):
- Company name, stage, sector, geography (required for context creation)
- Current cash balance and date (critical for runway — the #1 cause of incomplete reports)
- Monthly burn rate, unless the conversation already states it

**Stage is the one field of the four with a real fixed label set — use it verbatim, do not improvise.**
Options: `Pre-seed` / `Seed` / `Series A` / `Series B+`
→ `pre-seed | seed | series-a | series-b` (four options is the tool's max; the shared context script's `VALID_STAGES` enum has 7 values including `series-c`/`series-d`/`later`, so on a `Series B+` pick, ask a plain-text follow-up for the specific stage — do not default to `series-b`). Company name, sector and geography cannot take fixed labels (a proper noun, an open sector taxonomy, an open location) — shape them per the next paragraph instead.

**IMPORTANT:** Always use the `AskUserQuestion` tool for founder questions — never ask as plain chat text. **If `AskUserQuestion` is genuinely unavailable in the host, do NOT skip the ask and do NOT assume the answer:** ask the same question in plain chat, state the options explicitly, and wait for an answer before continuing. The tool provides a structured UI that renders correctly in Cowork. Always provide at least 2 options (the tool requires a minimum of 2). **Construct those two options concretely so every question is answerable** — never emit a single-option question or a bare free-text prompt (a free-text answer that matches no option dead-ends the run). For each founder question give: (1) an affirmative option carrying the likely value — for the company name that includes **"Use what the model file states"** (the Step-1 staging branch above resolves that answer safely, so it is a valid choice, not a trap); and (2) a **"Not stated — proceed and flag to confirm"** fallback so the founder can always move forward. Cash balance, date and burn rate follow the same two-option shape — an affirmative carrying whatever value was already stated in the conversation or files, plus the "Not stated" fallback; these are runtime-labelled (dollar amounts and dates), not a fixed label set.

**When there is NO file, "Use what the model file states" is not an answerable option** — there is no file to read it from, so offering it costs a round-trip and then a second question. On a conversational or deck-only run, build the company-name question from what you actually have instead: an affirmative option carrying the name **as it appeared in the conversation or on the deck's title slide** (say where you got it, so the founder is confirming rather than re-supplying), plus the "Not stated" fallback. The same holds for sector and geography.

**Why everything upfront:** Extraction sub-agents run in parallel and cannot pause to ask questions. Asking early prevents pipeline stalls.

**Each question is a recorded gate: open, ask, answer.** Open them in one call before asking (on a quick check drop the three `fmr_cash_basics` gates; after Exit 0 the company questions are already settled, which `open` reports). Ask from the printed `needs_input`, then record each reply with the `answer_command` it printed (`stated` takes the figure as `--value`). A figure the conversation already gave is recorded, not asked: `python3 "$SHARED_SCRIPTS/record_gate_answer.py" default --run-id "$RUN_ID" --artifacts-root "$ARTIFACTS_ROOT" --gate <gate> --reason stated_in_request --answer-id stated --value "<figure>"`. A `Series B+` reply opens the follow-up (`ctx_stage_detail`): ask and record it the same way. <!-- gate: ctx_stage_detail -->

```bash
python3 "$SHARED_SCRIPTS/record_gate_answer.py" open --run-id "$RUN_ID" --artifacts-root "$ARTIFACTS_ROOT" \
  --gate ctx_basics.company_name --gate ctx_basics.stage --gate ctx_basics.sector --gate ctx_basics.geography \
  --gate fmr_cash_basics.current_balance --gate fmr_cash_basics.balance_date --gate fmr_cash_basics.monthly_burn
```

If the founder provides files (Excel/CSV), still ask about cash balance — extraction may miss or misinterpret values, and having the founder's stated number lets the agent cross-check later.

**Company name deferred to the model file — stage the extraction FIRST (avoids the slug-ordering deadlock):** If the founder does not give a company name and defers it to the uploaded model (e.g. answers the name question with "use the model file"), the name requires the extraction, which normally targets `$REVIEW_DIR`, which requires the slug, which requires the name — a deadlock. Do **not** resolve it by improvising a temp file or a provisional review dir under the outputs mount: that mount is append-only (Step 0) and the later `rm`/`mv` of the provisional path is a delete that rule forbids. Instead, stage the extraction to `$STAGING_DIR` (the `/tmp` dir from Step 0 — safe to both create and reclaim; its `${SLUG:-fmr}` default already tolerates being created before the slug is known), derive the name from the staged output, run `init` below, then `cp` the staged file into `$REVIEW_DIR`:

```bash
# 1. Stage the extraction OUTSIDE the outputs mount (pre-slug):
python3 "$SCRIPTS/extract_model.py" --file <path> --pretty -o "$STAGING_DIR/model_data.json"
# 2. Read the company name from $STAGING_DIR/model_data.json (company_name field / model header).
# 3. Run `founder_context.py init` (below) with the derived --company-name; it prints the context
#    JSON including "slug" — read the slug from that printed output. Do not capture python output
#    into a shell variable.
# 4. Create $REVIEW_DIR (Step 0's mkdir, now that the slug is known), then copy the staged file in
#    — a plain write, append-only-safe:
cp "$STAGING_DIR/model_data.json" "$REVIEW_DIR/model_data.json"
```

Then continue from Step 2's periodicity check as normal (the staged extraction already ran). **Never** create a provisional review dir or temp file anywhere under the outputs mount, and **never** rename or move a review dir. Extraction runs ONLY via the documented invocations — Step 2's `$REVIEW_DIR` target or this Exit-1 `$STAGING_DIR` staging block — never an ad-hoc `extract_model.py` call with improvised flags or targets.

Then create (exit 10 names a question not yet recorded: ask it, record it, run `init` again):

```bash
python3 "$SHARED_SCRIPTS/founder_context.py" init \
  --company-name "Acme Corp" --stage seed --sector "B2B SaaS" \
  --geography "US" --artifacts-root "$ARTIFACTS_ROOT" \
  --run-id "$RUN_ID" --skill financial-model-review
```

If the script prints a `sector_type` warning but exits 0, that's non-fatal — proceed without retrying. However, a null `sector_type` may suppress sector-specific checklist gating downstream. If you know the correct type, re-run with `--sector-type` (valid values: `saas`, `ai-native`, `marketplace`, `hardware`, `hardware-subscription`, `consumer-subscription`, `usage-based`, `transactional-fintech`, `retail`).

**Exit 10 (several companies):** ask which company via `AskUserQuestion` from the printed `needs_input` (its labels are the company names found on disk), record it with its `answer_command`, then re-read with `--slug`; `A different company` → as Exit 1. <!-- gate: ctx_select_company --> Exit 1 with another `code`: report it and stop.

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
- **Two ways to finish, and only two:** run the full pipeline to completion, or run the quick-check path (Step 5-quick), which still runs the producer the question needs. Both end
  with real artifacts on disk. Anything else is not a finished run.
- **If you are blocked, say BLOCKED and say why.** A missing input, a failed hand-off, an unreadable
  document — name it and stop. Do not substitute your own reasoning for the pipeline and present the
  result as its output.

Artifact existence is the proof of execution: if no canonical artifact was written, the skill did not
run, whatever the transcript says.

### Step 2: Extract Model Data

**When Excel (.xlsx) or CSV files are provided,** run `extract_model.py` directly in the main thread:

```bash
python3 "$SCRIPTS/extract_model.py" --file <path> --pretty -o "$REVIEW_DIR/model_data.json"
```

Check the `periodicity_summary` and per-sheet `periodicity` fields. If periodicity is `quarterly` or `annual`, all **flow metrics** (burn, revenue, expenses — anything measured per period) must be divided by 3 or 12 respectively in the next step. Do NOT convert stock metrics (cash balance, headcount, customer count, ARR — point-in-time snapshots). If periodicity is `unknown`, flag it.

**When documents (PDFs, data room dumps, Google Sheets exports) are provided:** Extract what you can directly from the documents, consulting `${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/references/schema-inputs.md` for the schema and `${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/references/data-sufficiency.md` for sufficiency assessment. Write a provisional `inputs.json`.

**When conversational input is provided (no files):** Gather all needed fields within Step 1 through normal conversation. Consult `${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/references/schema-inputs.md` for the full schema.

### Context A hand-off protocol (file transport + gate)

Every Context A dispatch prompt carries an `OUTPUT_PATH:` line built from `$HANDOFF_AGENT`. The
sub-agent WRITES its output JSON to that path with its Write tool and returns only a small receipt:
`{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}`. The payload leaves the model
exactly once (into the Write call) — never re-type sub-agent JSON into a heredoc.

**`$HANDOFF_AGENT` and `$HANDOFF_DIR` name the SAME directory by two different paths — they are not
interchangeable.** `$HANDOFF_DIR` is the absolute VM path your shell uses (`python3`, `check_handoff.py`,
producer pipes). `$HANDOFF_AGENT` is the absolute file-tool path of the same directory (proven at
Step 0), and it is the ONLY one that goes in a dispatch prompt. Putting `$HANDOFF_DIR` in an
`OUTPUT_PATH` line hands the sub-agent an absolute `/sessions/...` path the host-loop gate denies;
putting `$HANDOFF_AGENT` in a shell command resolves it against the wrong cwd. Rule of thumb: **agent
namespace in prompts, shell namespace in bash.**

**The receipt is the ONE exemption from the never-re-type rule.** "Never re-type" governs the
*payload* — the extraction JSON, the coaching commentary, anything the founder's numbers pass through.
The receipt is a two-field acknowledgement the sub-agent returns in its final message, and reading
`output_path` out of it to pass to `check_handoff.py --agent-path` is expected, not a violation. If it
were forbidden, the hand-off could not be gated at all.

**Path idiom for dispatch prompts (host-loop path gate):** `OUTPUT_PATH` and any under-outputs artifact
READ path a sub-agent is given are **absolute file-tool paths**, never relative ones (a relative
file-tool path is refused) —
built from the `resolve_artifacts_root.py --agent` namespace (`$HANDOFF_AGENT` / `$REVIEW_DIR_AGENT`).
Never hand a sub-agent an absolute `/sessions/...` path for a file-tool Read/Write — the host-loop path
gate denies it (steering shell work to the `bash` tool instead). Bundled `references/*.md` are the one
exception: pass them as the literal `${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/references/...`
token (it is pre-resolved to a host-readable path), never the shell's path to the plugin folder.

**After EVERY Context A dispatch, gate before piping** (`<step>` = the dispatch's file stem):

```bash
printf '%s' '<agent final message verbatim>' | \
  python3 "$SHARED_SCRIPTS/check_handoff.py" "$HANDOFF_DIR/<step>_output.json" \
    --agent-path "$HANDOFF_AGENT/<step>_output.json" --receipt-json -
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

Branch on the exit code (complete state machine — do not improvise):

- **Exit 0** → pipe the file through the producer: `cat "$HANDOFF_DIR/<step>_output.json" | python3 "$SCRIPTS/<producer>.py" ...`
- **Exit 3** (missing/empty file — receipt may be fabricated) → **redo-dispatch**: fresh Task, same prompt plus one line: "your receipt claimed a file at `<path>` but none exists; use Write to create exactly that path." For the generated CHECKLIST prompt, re-run `fmr_dispatch_prompt.py` with the same arguments plus `--correction missing-file` and send that output instead.
- **Exit 4** (file exists, invalid JSON) → **repair-dispatch**: fresh Task: "Read `<OUTPUT_PATH>`; it fails JSON parsing with `<verbatim detail from the diagnostic>`; fix and rewrite it; return the receipt."
- **Exit 5** (receipt echoes a different path) → **repair-dispatch** telling the agent the exact expected OUTPUT_PATH (it wrote somewhere else).
- **Exit 6** (receipt unparseable / no `output_path` key) → **redo-dispatch** with "return ONLY the receipt JSON — no fences, no prose." For the generated CHECKLIST prompt, use `--correction receipt-only`.
- **Producer schema rejection** (the pipe fails next) → **repair-dispatch** with the producer's stderr verbatim. For the generated CHECKLIST prompt, re-run the failed pipe with `2> "$HANDOFF_DIR/producer_rejected.txt"`, then `fmr_dispatch_prompt.py` with the same arguments plus `--correction producer-rejected --detail-file "$HANDOFF_DIR/producer_rejected.txt"`, and send that output.
- **Exit 8** (`path_namespace_mismatch`) → the sub-agent **complied**; the agent-namespace prefix was wrong. Its relative `OUTPUT_PATH` resolved against the outputs mount instead of the session root, so the file landed at the doubled path reported in `found_at`. Only a RELATIVE agent path can do this, so the Step 0 proof did not run: run it. Do NOT treat this as a fabricated receipt (that is exit 3), and do NOT read the hand-off from `found_at` — it is diagnostic only. Re-run `resolve_artifacts_root.py --agent`, rebuild the agent-namespace prefix from the printed value, and re-dispatch. Counts against the same 2-dispatch retry budget.
- **Blocked `write_refused`** (the sub-agent's Write was refused — its path was relative or a `/sessions/...` path) → run the Step 0 proof if it did not run, rebuild the agent-namespace paths from the resolver, re-dispatch ONCE. A second `write_refused` STOPs with both details quoted.
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
stage to `$STAGING_DIR/<step>_input.json`; same producer pipe), and tell the founder in one plain sentence that this run's working files were passed
directly instead of through `outputs/`, so its audit trail is incomplete (the results are unaffected).
A refused write is NOT this case: it returns `write_refused` (above).

Retries overwrite the same OUTPUT_PATH (nothing under the outputs mount is deleted, by this skill's rule — never `rm`
under `$REVIEW_DIR`). Hand-off files are not canonical artifacts: producers consume them only via
the explicit pipe, and `compose_report.py` never reads `handoff/`.

Ad-hoc scratch (NOT sub-agent hand-off) still goes to `$STAGING_DIR` in `/tmp` — see the reference
(`founder-skills/references/skill-execution-model.md`). Hard rule: never stage scratch anywhere under
the outputs mount (which includes `$REVIEW_DIR`), and never delete anything under it — see the
append-only rule in Step 0.

### Step 3: INPUTS_REVIEW Dispatch (Context A)

**FIRST — branch on `model_format`. This dispatch only applies to file input.**

- **`spreadsheet` or `partial`** (the founder attached a model): `model_data.json` exists from Step 2's
  extraction. Dispatch INPUTS_REVIEW as documented below.
- **`conversational` or `deck`** (the founder typed the numbers, or they came from a deck): **there is
  no `model_data.json` and there never will be** — nothing was extracted, so there is nothing for this
  dispatch to review. Author `inputs.json` directly from what the founder stated, **skip the
  INPUTS_REVIEW dispatch entirely**, and go to Step 3.5 (`validate_inputs.py`).

This branch is load-bearing because the dispatch template below hardcodes "Read model_data.json …
(the full extraction output)". Sent on a conversational run, the sub-agent is asked for a file that
does not exist — and the failure mode is not a clean error but an improvisation: it reconstructs
plausible-looking values, or the main thread abandons the pipeline and hand-computes in chat. Sparse
input is a legitimate input shape here, not a degraded one; see `validate_inputs.py`'s
`sparse_by_design` handling.

**Dispatch the financial-model-review sub-agent in Context A (INPUTS_REVIEW).** **Call the `Task` tool with `subagent_type: "founder-skills:financial-model-review"`** and the prompt below. This is the highest context-pressure dispatch — the sub-agent reads the full `model_data.json` inside its own context window and returns only the corrected `inputs.json`. This is the primary Mitigation 1 win: the raw extraction output never accumulates in the main thread context.

**Before dispatching, substitute placeholders in the template below:** replace `<HANDOFF_AGENT>` and `<REVIEW_DIR_AGENT>` with the agent-namespace values (from `resolve_artifacts_root.py --agent` — absolute file-tool paths, proven at Step 0; NOT absolute `/sessions/...` paths, which the host-loop gate denies) and `<RUN_ID>` with `$RUN_ID`. Leave the `${CLAUDE_PLUGIN_ROOT}/...` reference paths **literal** — they are pre-resolved to a host-readable path. The sub-agent has no access to your shell variables.

**Dispatch prompt template:**

```
CONTEXT: INPUTS_REVIEW
OUTPUT_PATH: <HANDOFF_AGENT>/inputs_review_output.json
RUN_ID: <RUN_ID>

You are the financial-model-review agent dispatched in Context A (INPUTS_REVIEW).
Read model_data.json at <REVIEW_DIR_AGENT>/model_data.json (the full extraction output).
If a reference path below cannot be read (refused or not found), read the same file under the plugin folder your own instructions name.
Also read:
  - ${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/references/schema-inputs.md
  - ${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/references/extraction-pitfalls.md
  - ${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/references/data-sufficiency.md

Construct a complete, valid inputs.json from the extracted data. Apply all
extraction pitfall checks (scale denomination, ARPU sanity, periodicity
conversion, company name sourcing, payroll aggregation, collections vs revenue).

ARPU sanity check: if drivers.arpu_monthly or unit_economics.ltv.inputs.arpu_monthly
exceeds total MRR, it is probably aggregate revenue, not per-customer ARPU —
divide by customer count.

Currency: PRESERVE the model's native currency — never force-convert to USD.
Set the top-level "currency" field to the model's native ISO 4217 code (e.g.,
"USD", "INR", "ILS"). If the model states its own FX rate, record it as a note
in metadata but do NOT apply it to convert any values. Absent "currency" is
treated as USD-equivalent downstream, so leaving it unset for a non-USD model
is itself an error — always set it explicitly to the native code.

Use your Write tool to write to OUTPUT_PATH. Shape (do NOT include a "changes"
or "base_hash" key — those belong to the founder browser round-trip, not this
dispatch):
{
  "corrected": {<full validated inputs.json contents per schema-inputs.md,
                 including "metadata": {"run_id": "<RUN_ID>"}>},
  "corrections": [
    {"path": "cash.current_balance", "old": null, "new": 1500000,
     "reason": "<where the value came from / what was fixed>"}
  ]
}
The "corrections" array is the audit trail written to extraction_corrections.json.
Then return ONLY the receipt JSON in your final assistant message:
{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}
Do NOT write any file other than OUTPUT_PATH — you never write a canonical
artifact; anything else you write bypasses schema validation and
run_id stamping.
```

**After the sub-agent returns:** gate the hand-off per the Context A hand-off protocol.

**INPUTS_REVIEW special handling — file-args-based script:** Unlike other dispatch points, `apply_corrections.py` takes file arguments, not stdin. The hand-off file IS the file argument — no re-typing needed. The main thread must:

1. If `inputs.json` does not yet exist, write an empty inputs stub first:
   ```bash
   echo '{}' > "$REVIEW_DIR/inputs.json"
   ```
2. Run `apply_corrections.py` with the gated hand-off file as its argument:
   ```bash
   python3 "$SCRIPTS/apply_corrections.py" "$HANDOFF_DIR/inputs_review_output.json" \
     --original "$REVIEW_DIR/inputs.json" \
     --output-dir "$REVIEW_DIR" --run-id "$RUN_ID" --origin inputs_review
   ```
   <!-- skill-quality-ci: bash-after-subagent-ok -->
3. `apply_corrections.py` prints an `Info: corrected-object payload (dispatch shape)` line to
   stderr for `corrected`-shaped payloads — that is expected, not an error.
   Read the stdout JSON:
   - If `status == "completed"`: promote `corrected_inputs.json` to `inputs.json`. Use `cp`, not
     `mv` — `mv` deletes the outputs-side source, which the append-only rule (Step 0) forbids; `cp`
     overwrites `inputs.json` in place and leaves `corrected_inputs.json` (an allowlisted artifact):
     ```bash
     cp "$REVIEW_DIR/corrected_inputs.json" "$REVIEW_DIR/inputs.json"
     ```
   - If `status == "error"` (coercion or time-series validation failed): treat it as a
     producer schema rejection per the hand-off protocol — repair-dispatch with the
     `errors` array verbatim, re-gate, and re-run step 2. Only as a last resort write
     `inputs.json` directly from `corrected` — Step 3.5's validate_inputs gate must
     then catch what coercion would have.

### Step 3.5: Validate `inputs.json` — STOP GATE

Run the validation script:

```bash
cat "$REVIEW_DIR/inputs.json" | python3 "$SCRIPTS/validate_inputs.py" --pretty
```

If `valid == false` (errors present), run with `--fix` to auto-correct fixable issues:

```bash
# validate_inputs.py consumes stdin fully BEFORE writing -o, so read-from and write-to the same file is
# race-free — writes inputs.json in place, no temp/mv (mv would delete an outputs file, which the append-only rule forbids).
python3 "$SCRIPTS/validate_inputs.py" --fix < "$REVIEW_DIR/inputs.json" -o "$REVIEW_DIR/inputs.json"
```

Then re-validate. If errors persist after `--fix`, correct `inputs.json` manually.

Also run the extraction validation script to cross-reference `model_data.json` against `inputs.json` (if `model_data.json` exists):

```bash
python3 "$SCRIPTS/validate_extraction.py" --inputs "$REVIEW_DIR/inputs.json" --model-data "$REVIEW_DIR/model_data.json" --fix --pretty -o "$REVIEW_DIR/extraction_validation.json"
```

**Do NOT proceed to Step 4 until `valid == true` and `has_critical_warnings == false`.**

### Step 3.6: Review Extracted Values

A recorded gate: open it first, show the values (Path A or B), ask the question below, record the reply.

```bash
python3 "$SHARED_SCRIPTS/record_gate_answer.py" open --run-id "$RUN_ID" --artifacts-root "$ARTIFACTS_ROOT" --gate fmr_extracted_values
```

If it printed `"applied": "pre_answer"`, the request already answered it: build no page, ask nothing, go to Step 4. (Resumed here with `corrections_applied` in the request: promote `corrected_inputs.json` and re-run Step 3.5 before this `open`.)

**Path A — File extraction** (`model_format` is `spreadsheet` or `partial`): build the HTML review page for the founder to inspect the extracted values. Always build the page in **static mode** — it works wherever the founder opens it, whereas a local server's address opens only on the machine running it:

```bash
python3 "$SCRIPTS/review_inputs.py" "$REVIEW_DIR/inputs.json" --static "$REVIEW_DIR/review.html" --extraction-warnings "$REVIEW_DIR/extraction_validation.json"
```

Send `review.html` to the founder as a file, with the host's file-delivery tool where one is offered (as Step 12 sends the finished documents) — never a bare path there; in a local terminal that offers none, give its absolute path — then ask via `AskUserQuestion` (the question below).

Use **server mode** only when the founder asks for live validation while editing and the session is a local command-line terminal on the founder's own computer:

```bash
python3 "$SCRIPTS/review_inputs.py" "$REVIEW_DIR/inputs.json" --workspace "$REVIEW_DIR" --extraction-warnings "$REVIEW_DIR/extraction_validation.json" &
```

Wait for the founder to say done, then kill the server and apply corrections.

**Path B — Conversational** (`model_format` is `conversational` or `deck`): present a confirmation table, then ask the same question with `AskUserQuestion`.

**The table is not a fixed list of eight fields.** Start from stage, MRR, growth rate, burn, cash,
customers, CAC and target raise — then add **every other field you are about to write that the founder did
not state.** The rule is: *if you supplied it and they did not, it goes in the table.* A field you
defaulted is exactly the field they cannot check anywhere else.

Then record which ones you supplied, in `inputs.json`:

```json
"agent_supplied": ["bridge.runway_target_months"]
```

Use `[]` when the founder stated everything — an empty list is a declaration, an absent field is not.
`validate_inputs.py` raises `UNDECLARED_AGENT_VALUE` on a conversational run that carries a
computation-feeding field with no declaration.

Why: without it a value you supplied is recorded indistinguishably from a stated one, so nothing downstream
(the checklist, a sub-agent, the founder re-reading their file) can tell the difference.

**This is a STOP point — do not proceed to Step 4 until the founder responds.** Step 4 refuses until the reply is recorded. The founder is the last check on the numbers before math runs on them. It matters *more* here, not less: a figure typed in conversation or read off a deck slide may be a
rounded estimate, a stale number, or an annual figure the reader took as monthly.

**The question, on either path:** "Do the extracted values look right?"
Options: `Looks right, proceed` / `I have corrections` / `Proceed without reviewing the extracted values`

Record the reply with the printed `answer_command` (`I have corrections` takes `--value`: how they will send them). Corrections go through `apply_corrections.py` whichever way they arrive — never edit `inputs.json` by hand, so the same coercion, path check and audit record apply. An uploaded corrections file, or one `--set` per field stated in chat (a value is read as a number, boolean or null where it parses as one and as text otherwise):

```bash
python3 "$SCRIPTS/apply_corrections.py" <uploaded-file> --original "$REVIEW_DIR/inputs.json" --output-dir "$REVIEW_DIR" --run-id "$RUN_ID" --origin upload
python3 "$SCRIPTS/apply_corrections.py" --set revenue.mrr=45000 --set cash.current_balance=1200000 --original "$REVIEW_DIR/inputs.json" --output-dir "$REVIEW_DIR" --run-id "$RUN_ID" --origin chat
```

A path that does not exist in `inputs.json` is refused rather than created, so a misheard field name stops here instead of becoming a new key. Then promote `corrected_inputs.json` to `inputs.json` (as in Step 3), re-run Step 3.5, and record `--answer-id corrections_applied` with the same command (refused unless this run's corrections call is on record).

### Step 4: Unit Economics and Runway (direct — no dispatch)

These two producers consume `inputs.json` verbatim. Run them directly from the
on-disk file — do NOT round-trip the JSON through a sub-agent (an LLM re-typing
multi-KB financial JSON risks silently corrupting numbers, and it saves no
context since the JSON would land in the main thread anyway):

```bash
# Step 0 already resolved PLUGIN_ROOT once, deterministically — reuse its printed
# value here rather than re-running the self-heal search in this fresh shell.
SCRIPTS="<printed PLUGIN_ROOT>/skills/financial-model-review/scripts"
cat "$REVIEW_DIR/inputs.json" | python3 "$SCRIPTS/unit_economics.py" --pretty --run-id "$RUN_ID" -o "$REVIEW_DIR/unit_economics.json"
cat "$REVIEW_DIR/inputs.json" | python3 "$SCRIPTS/runway.py" --pretty --run-id "$RUN_ID" -o "$REVIEW_DIR/runway.json"
```

Exit 10 from either is a question, not a failure (`-o` is left as it was): the values review (Step 3.6) or a cash question (Step 1) has no record for this run, or `inputs.json` changed after it was confirmed. Ask the gate its JSON names (`blocked_by_gate`), record it, run the step again.

Both scripts propagate `metadata.run_id` from `inputs.json` into their outputs
(required by the Context B run_id-parity check). They run BEFORE the checklist because the
checklist grades against their figures; both are pure functions of `inputs.json`, which is what
keeps the checklist's inputs fingerprint a sufficient staleness check. All metric fields are optional —
missing data yields `not_rated` / a partial-analysis stub, never a crash.

### Step 5: CHECKLIST Dispatch (Context A)

**Dispatch the financial-model-review sub-agent in Context A (CHECKLIST).** **Call the `Task` tool with `subagent_type: "founder-skills:financial-model-review"`.**

**The prompt is printed, not written.** Run the generator and send the printed text as the prompt,
unchanged — nothing added, removed or reworded, including on a re-run.

Run the generator in a shell call of its own — nothing before it but variable assignments, nothing after it — and send what it prints unchanged.

```bash
# A fresh shell: set each value again from Step 0's printed output (an empty one is refused).
RUN_ID="<Step 0 run id>"
HANDOFF_AGENT="<Step 0 printed value>"
REVIEW_DIR_AGENT="<Step 0 printed value>"
REVIEW_DIR="<Step 0 review dir>"
python3 "$SCRIPTS/fmr_dispatch_prompt.py" checklist --run-id "$RUN_ID" \
  --handoff-agent "$HANDOFF_AGENT" --review-dir-agent "$REVIEW_DIR_AGENT" --review-dir "$REVIEW_DIR"
```

**After the sub-agent returns:** gate the hand-off per the Context A hand-off protocol, then pipe:

```bash
cat "$HANDOFF_DIR/checklist_output.json" | \
  python3 "$SCRIPTS/checklist.py" --pretty --run-id "$RUN_ID" \
    --inputs "$REVIEW_DIR/inputs.json" -o "$REVIEW_DIR/checklist.json"
```
<!-- skill-quality-ci: bash-after-subagent-ok -->

### Step 7: Compose and Validate Report

```bash
python3 "$SCRIPTS/compose_report.py" --dir "$REVIEW_DIR" --pretty \
  -o "$REVIEW_DIR/report.json" \
  --write-md "$REVIEW_DIR/report.md"
```

`compose_report.py` writes both `report.json` and `report.md` deterministically. **Do NOT** read `report_markdown` out of `report.json` and re-write it via heredoc.

Check `validation.warnings`: fix high-severity (corrupt/missing artifacts), present medium-severity (checklist failures, runway inconsistencies, metrics gaps, unsupported comparisons) in the report, note low/info. `--strict` only blocks on high-severity warnings. Fix high-severity warnings, re-deposit, re-compose.

**Post-write verification:** `compose_report.py` exits non-zero (code 2) if the declared output files don't exist or are empty after writing. Exit 10 is a question, not a failure: ask the gate its JSON names (`blocked_by_gate`) — for `fmr_extracted_values` that is Step 3.6 again, then Steps 4–5 — record it, and compose again; never re-run compose without the answer. Any other non-zero exit: stop and report the exact stderr — do not proceed.

### Verification Gate 1 (after compose)

```bash
python3 "$SCRIPTS/verify_review.py" --dir "$REVIEW_DIR" --gate 1 --pretty
```

**If exit code is non-zero:** read `summary.errors`. Fix the issue by re-running the failing step, then re-run `verify_review.py --gate 1`. **Do not proceed until it exits 0.**

**Honest degradation vs. a real gap.** A gate that *passes* (exit 0) while carrying warnings about partial or insufficient data — for unit economics OR runway — is the sanctioned honest-degradation route: note the warnings in the report narrative and proceed. A warning is not a failure to fix. A hard gate *error* of the too-few-metrics / no-runway-scenario class means a stale or hand-authored artifact: the producers (`unit_economics.py`, `runway.py`) always self-declare insufficiency via an `insufficient_data` (or skipped-stub) flag, so re-run the corresponding producer from `inputs.json` — the fresh artifact self-declares and the gate then accepts with a warning. Any gate error unfixable from the model's own data → the qualitative/stub path in `${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/references/data-sufficiency.md`. **Never fabricate a value to satisfy a gate, and never read the skill's script source to debug a gate — the gate contract is documented in data-sufficiency.md, not in the scripts.**

### Step 7.5: Write Commentary (agent-authored, required for quantitative reviews)

`verify_review.py --gate 2` requires `commentary.json` whenever `unit_economics.json`
and `runway.json` are real (non-stub) — and `explore.py` embeds it into the
interactive explorer. Author it now, in the main thread, from the artifacts you
have already seen (checklist summary, unit-economics ratings, runway scenarios).
Schema: `${CLAUDE_PLUGIN_ROOT}/skills/financial-model-review/references/artifact-schemas.md` § commentary.json. `headline` is required;
include only the lens keys whose artifacts exist (valid lens keys: `runway`,
`unit_economics`, `stress_test`, `raise_planner`).

```bash
cat > "$REVIEW_DIR/commentary.json" <<'COMMENTARY_EOF'
{
  "headline": "<one-sentence financial health summary>",
  "investor_talking_points": [
    "<sentence the founder can say out loud during a fundraise conversation>"
  ],
  "lenses": {
    "runway": {"callout": "<key insight>", "highlight": "<secondary observation>", "watch_out": "<risk>"},
    "unit_economics": {"callout": "<key insight>", "watch_out": "<risk>"}
  }
}
COMMENTARY_EOF
```

Ground every sentence in artifact values — never invent numbers. If both
`unit_economics.json` and `runway.json` are skipped stubs (qualitative path),
skip this step; Gate 2 will not require the file.

### Steps 8a-8b: Visualize and Generate Explorer (Optional)

```bash
python3 "$SCRIPTS/visualize.py" --dir "$REVIEW_DIR" -o "$REVIEW_DIR/report.html" --run-id "$RUN_ID"
python3 "$SCRIPTS/explore.py" --dir "$REVIEW_DIR" -o "$REVIEW_DIR/explore.html" --run-id "$RUN_ID"
```

Generate files silently — present paths after Gate 2 passes.

### Step 8c: Post-Compose Coaching Commentary (Context B dispatch — POST_COMPOSE_COACHING)

**Dispatch the financial-model-review sub-agent in Context B.** **Call the `Task` tool with `subagent_type: "founder-skills:financial-model-review"`** after `compose_report.py` has successfully written both `report.json` and `report.md`.

**Mitigation 2 protocol:** the main thread reads the structured `coaching_payload` from `report.json` and STAGES it as a file in the hand-off dir; the sub-agent Reads it from the agent namespace (a functionally required read, so a wrong prefix fails loudly before anything is written). The sub-agent does NOT Read full `report.md` — it consumes the staged `coaching_payload.json` directly, composes the coaching commentary, and **WRITES it as plain markdown to the `OUTPUT_PATH` hand-off file (a `.md` file) with its Write tool — no JSON, no escaping — returning only a small receipt** (the same file transport as Context A — the commentary leaves the model exactly once, into the Write call; the main thread never re-types it). The main thread gates that file with `check_handoff.py --format=markdown`, transforms it into the JSON transport envelope with `md_to_commentary.py` (deterministic escaping — `json.dumps` cannot emit malformed JSON), then pipes it into the shared `insert_coaching.py` script (idempotency matrix, uuid-marker replacement, run_id-parity verification — all deterministic, unchanged). See the financial-model-review agent body's "Context B — Post-compose coaching dispatch (POST_COMPOSE_COACHING)" section for the full procedure.

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

You are dispatched to add coaching commentary to a financial model review.

The compose_report.py script has finished. Its structured `coaching_payload` has
been STAGED AS A FILE for you — it is not inlined in this prompt.

Read the coaching payload at <HANDOFF_AGENT>/coaching_payload.json. That file is
your COMPLETE input. Do not supplement it with narrative company context, your
own recollection of the conversation, or anything from report.md — the commentary
is appended to the same investor-facing report that carries the scored figures, so
anything you add that is not in the payload can contradict the numbers beside it.

If that Read FAILS, write NO file and return exactly:
{"status": "blocked", "reason": "handoff_path_unresolvable", "attempted": "<the path you tried>"}
Do not Glob for it, do not guess a different prefix, do not proceed from memory —
a failed Read here means the hand-off prefix is wrong and the main thread must
re-issue the dispatch. Reporting it is the correct outcome.

Follow your agent body's Context B procedure (POST_COMPOSE_COACHING):

1. Compose commentary from the STAGED coaching_payload (failed_items,
   warned_items, summary, score_coverage, high_severity_warnings, company_name).
   If truncated:true, acknowledge that not all failures are shown.
   If `score_coverage.complete` is false, the score was computed over fewer criteria
   than this company warrants (`not_assessed_count` of `total_criteria`). TWO causes, and
   either or BOTH may apply: a non-empty `unmatched_profile_fields` means we could not match
   that detail of the company, and checks may ALSO have been set aside during the assessment
   itself (the count covers both). Name what the payload supports; never present `overall_status` as a clean
   headline. That is a gap in the review — not a strength, and not a criticism.
   Do NOT Read the full report.md. Do NOT edit report.md or any canonical artifact.
   The commentary is appended to the founder's report, so write it in their language:
   never a checklist item id, a status enum (`not_applicable`), a warning code, or one of
   our filenames. `high_severity_warnings` now carries a readable `label` beside each
   `code` — use the label.
     Instead of: "UNVALIDATED_CLAIMS on the runway figure"
     Write:      "the runway figure is not backed by anything in the model"
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

**After the sub-agent returns:** if its final message is a `{"status": "blocked", "reason": ...}` object, stop and report the reason to the founder — do not run the gate. The one exception is `write_refused`: run the Step 0 proof if it did not run, rebuild `<HANDOFF_AGENT>` from the resolver, and re-dispatch once; a second `write_refused` stops. Otherwise gate the hand-off, then (on gate exit 0) transform and insert deterministically. **The commentary leaves the model exactly once (into the sub-agent's Write call) — NEVER re-type the sub-agent's markdown into a heredoc or a `python -c` argument.**

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
    --report-json "$REVIEW_DIR/report.json" \
    --marker '<EXACT insertion_marker string from report.json coaching_payload>' \
    --verify-artifact "$REVIEW_DIR/inputs.json" \
    --verify-artifact "$REVIEW_DIR/checklist.json" \
    --verify-artifact "$REVIEW_DIR/unit_economics.json" \
    --verify-artifact "$REVIEW_DIR/runway.json"
```

The gate (`check_handoff.py --format=markdown`) verifies the sub-agent's hand-off file exists, is non-empty, matches the receipt's echoed path, and passes the content-shape gate (not receipt-shaped, no marker collision); `md_to_commentary.py` wraps the raw markdown in the `{"commentary_markdown": ...}` envelope (escaping by construction via `json.dumps`); `insert_coaching.py` then performs the 6-state idempotency check, replaces the marker with `## Coaching Commentary` + the commentary in a single in-place write, and verifies `run_id` parity across all 4 producer artifacts (skipped stubs for `unit_economics.json`/`runway.json` carry a `metadata.run_id` too and verify identically). Branch on the exit code (complete state machine — do not improvise):

- **Exit 0 from the chain** — `insert_coaching.py`'s receipt on stdout says `inserted` (or `already_inserted` on a resume). Proceed to Verification Gate 2.
- **`check_handoff.py` exit 3** (missing/empty file — receipt may be fabricated) → **redo-dispatch**: fresh Task, same prompt plus one line: "your receipt claimed a file at `<path>` but none exists; use Write to create exactly that path."
- **Exit 5** (receipt echoes a different path) → **repair-dispatch** telling the agent the exact expected OUTPUT_PATH.
- **Exit 6** (receipt unparseable / no `output_path` key) → **redo-dispatch** with "return ONLY the receipt JSON — no fences, no prose." (A `status: "blocked"` final message is NOT exit 6 — it was handled before the gate.)
- **Exit 7** (content-shape gate failed — receipt-shaped or marker-bearing file) → **repair-dispatch**: "your file wasn't the coaching commentary — write the coaching markdown, nothing else, to `<OUTPUT_PATH>`."
- **Exit 8** (`path_namespace_mismatch`) → the sub-agent **complied**; the agent-namespace prefix was wrong. Its relative `OUTPUT_PATH` resolved against the outputs mount instead of the session root, so the file landed at the doubled path reported in `found_at` (only a relative path can do this: run the Step 0 proof). Do NOT treat this as a fabricated receipt, and do NOT read the hand-off from `found_at` — re-dispatch with the corrected agent-namespace prefix (re-run `resolve_artifacts_root.py --agent` and rebuild `<HANDOFF_AGENT>` from the printed value). Counts against the same 2-dispatch retry budget.
- **Any other exit** (script crash, unreadable file, invalid UTF-8) → STOP with the stderr. `check_handoff.py` exit 4 is reachable here too: gate 1 already confirmed the file exists and is non-empty, so a failure opening it afterwards is an IO/permission fault, not a malformed hand-off. A decode error raises before any typed exit and surfaces as a traceback.
- **`insert_coaching.py` exit 1** (blocked; stdout carries `{"status": "blocked", "reason": ...}`) → stop and report the exact reason. Do NOT hand-edit `report.md` — if the reason mentions a truncated report or a missing marker, re-run `compose_report.py --write-md` and retry the chain. If the reason is `commentary_markdown missing or empty`, treat as a malformed hand-off: repair-dispatch quoting the reason.
- **After ANY corrective dispatch, resume from the gate chain** — never feed the transform+insert pipe an ungated file.

**Retry budget:** max 2 corrective dispatches (same rule as Context A). **Graceful degrade:** if the FIRST corrective dispatch also exits 3 while the receipt claims `complete` with the correctly echoed path, treat the host topology as hand-off-incompatible and fall back to message-channel transport, and tell the founder in one plain sentence (see Context A's degrade rule). **The corrective dispatch MUST ask for the commentary inline for this to be reachable** — add: "the file hand-off is not working in this environment; return the coaching commentary itself as your final message, as raw markdown, with no receipt JSON and no fences." Without that line the fallback is unreachable: the normal Context B prompt instructs the agent to return ONLY the receipt and not to narrate, so its final message contains no markdown to stage. Then stage that returned markdown to `$STAGING_DIR/coaching.md` via a **single-quoted** `<<'COACHING_EOF'` heredoc (apostrophe-safe), and run the same `md_to_commentary.py "$STAGING_DIR/coaching.md" | insert_coaching.py` chain against that staged file.

### Step 8d: Cleanup

No cleanup needed: scratch lives in `$STAGING_DIR` (`/tmp`, reclaimed by the sandbox). **Do not `rm`
anything under `$REVIEW_DIR`** — it is the promoted `outputs/` tree in Cowork, where deleting a
user-visible path is unsafe (and the parity gate flags it).

### Verification Gate 2 (final)

```bash
python3 "$SCRIPTS/verify_review.py" --dir "$REVIEW_DIR" --pretty
```

**This is the final quality gate.** If it exits non-zero, fix the issues before presenting anything to the founder. Once it passes, Step 12 delivers `report.md`, `report.html` and `explore.html` and prints the hand-over.

**Do NOT inline `report_markdown` in the assistant message.** The founder reads the file. (Closing the ~80-130K context accumulation issue.)

**Presenting numbers to the founder:**
- Present the numbers from `report.md` **verbatim** — do not re-derive or restate them from memory or from intermediate context.
- For what-if questions (e.g., "what if we cut burn by 20%?", "what if revenue grows faster?"), direct the founder to `explore.html` for precomputed scenarios, or offer to re-run `runway.py` with a custom `--scenarios` block for new scenarios. Never estimate the answer by hand in chat.
- The report's footer line (generated by `compose_report.py`) already points the founder to the explorer for what-ifs.

### Step 12: Deliver Artifacts

**Send the finished work to the founder — the complete set, as files.** Not a path, and not a subset.
A path is not a deliverable in Cowork — whether the workspace it names outlives the task depends on how
that task was started, so a founder who was handed only a path may end up with nothing. (That is your
reason for sending files; it is not something to tell the founder — see the no-claims rule below.) Send
every finished document you produced for them, and frame them as results you generated rather than
something they asked to look at.

**Then hand them over by name — one named entry per document.** Sending the files and handing them
over are different acts: a founder looking at a row of cards cannot tell which document is which.
Write each deliverable into your message as its own named entry — a link where this surface renders
one that opens (on a `/sessions` session tree, `computer://` + the absolute path you just copied it
to), otherwise the label with the path stated beside it — labelled by what the document IS, in the
founder's words (the written report, the charts), not by its filename. "The files are above" is not a
hand-over. Where a step prints the hand-over, the printed entries are these. This does not conflict with the never-name-a-file rule: the founder reads your label,
never the path. Never paste a report's body into the message — link or name it.

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

Before sending them, close the run's file list (for a host; nothing to tell the founder):

```bash
python3 "<printed PLUGIN_ROOT>/scripts/run_status.py" deliverables --run-id "$RUN_ID" --artifacts-root "$ARTIFACTS_ROOT" --final || :
```

**In this skill the hand-over message is printed, not written.** It is the links, the report's own
verdict paragraph (the model's rating and its runway, with runway at today's burn when that is shorter),
and the offer. Send the files first; then run this as your LAST tool call:

```bash
python3 "$SCRIPTS/fmr_closing_message.py" --report "$REVIEW_DIR/report.json" \
  --deliverable "the written report=<absolute path of report.md>" \
  --deliverable "the charts=<absolute path of report.html>" \
  --deliverable "the what-if explorer=<absolute path of explore.html>"
```

Its printed output is your entire final message, character for character — every dash, line and link
as printed — with no summary, sources or note before or after it. Never compute or restate a figure around
it — runway, burn and scores come from the report, in the report's words.

Here the printed hand-over replaces the named entries and the offer described above: its archive offer
is the only offer made, and a connected folder is written to only if the founder asks.

**When the hand-over asked for the cash balance and the founder replies with it**, keep this run's
`RUN_ID` and `$REVIEW_DIR`. Record the balance as a plain number, its month as `YYYY-MM`, and the answer; promote; re-run runway: <!-- gate: fmr_cash_followup -->

```bash
python3 "$SCRIPTS/apply_corrections.py" --set cash.current_balance=<amount> --set cash.balance_date=<YYYY-MM> \
  --original "$REVIEW_DIR/inputs.json" --output-dir "$REVIEW_DIR" --run-id "$RUN_ID" --origin chat
python3 "$SHARED_SCRIPTS/record_gate_answer.py" answer --run-id "$RUN_ID" --run-dir "$REVIEW_DIR" \
  --gate fmr_cash_followup --answer-id provided --gate fmr_cash_basics.current_balance --answer-id stated \
  --value "<amount>" --gate fmr_cash_basics.balance_date --answer-id stated --value "<YYYY-MM>"
cp "$REVIEW_DIR/corrected_inputs.json" "$REVIEW_DIR/inputs.json"
cat "$REVIEW_DIR/inputs.json" | python3 "$SCRIPTS/runway.py" --pretty --run-id "$RUN_ID" -o "$REVIEW_DIR/runway.json"
```

Then Steps 7, 7.5 (runway lens), 8a-8c, Gates 1-2, this step, with `--cash-update` on the
closer, which states the update; its output stays your whole final message. Any other changed figure after
delivery needs a new review: this run's steps refuse it.

## Main-Thread Return

This skill runs inline in the main thread (not as a sub-agent). The final outcome the main thread delivers to the founder is:

- **In Claude Code:** the path to `$REVIEW_DIR/report.md` — there the path *is* the deliverable, because
  `./artifacts/` is durable. **In Cowork:** the delivered files are the deliverable; a path
  names a workspace that may not outlive the task.
- The printed hand-over from Step 12, unchanged: its verdict already states the rating and the runway
  (including runway at today's burn for a default-alive company, where the projected figure is
  "Infinite"). The headline fields in `coaching_payload` (`runway_months`, `static_runway_months`,
  `summary.overall_status`, `high_severity_warnings`) are for the coaching sub-agent; do not restate them
  in chat.

## Scoring

- Each of 46 items: pass / fail / warn / not_applicable
- `score_pct` = (pass + 0.5 * warn) / (total - not_applicable) * 100
- Overall: "strong" (>=85%), "solid" (>=70%), "needs_work" (>=50%), "major_revision" (<50%)

## Feedback

If a run ends **blocked or failed**, after you report the reason to the founder, add one line:
> _If this looks wrong or didn't finish, you can flag it: type `/founder-skills:feedback`._

On **unsolicited** praise or frustration, you may tell the founder they can type `/founder-skills:feedback` once — never routinely, never mid-workflow, never more than once per session.
