# Skill Execution Model

> Source of truth for how the founder-skills plugin executes skills
> across hosts (Claude Code, Claude Cowork). Read once; refer back
> when behavior is unexpected.

## Overview

Skills run in three dispatch contexts. Each context has a different
tool surface and different rules.

## Three Dispatch Contexts

### 1. Main Thread (SKILL.md Execution)

- Triggered when user invokes a skill (`/<skill-name>` or via Skill tool).
- Tool surface: full shell + Task + Read/Edit/Write/Glob/Grep. "Shell"
  is the literal `Bash` tool in the standalone CLI and most hosts;
  in Cowork it's `mcp__workspace__bash` (used transparently — the model
  doesn't branch on the name). Same for web fetch: literal `WebFetch`
  elsewhere, `mcp__workspace__web_fetch` in Cowork.
- Role: orchestrate the pipeline. Calls producer scripts via shell.
  Dispatches sub-agents via the Task tool for analytical work. The
  dispatch tool's name is runtime-dependent — labelled `Task` in Claude
  Code / Cowork and `Agent` in some newer builds — just as the shell tool
  is `Bash` vs `mcp__workspace__bash` above; the model doesn't branch on
  the label. What actually binds the scoped agent is the `subagent_type`
  pin (`subagent_type: "founder-skills:<skill>"`), NOT the tool name, so
  the SKILL.mds' literal "`Task` tool" wording is correct on every runtime
  regardless of which label that runtime shows.
- Each skill resolves its own per-engagement working directory under
  `outputs/artifacts/` at Step 0. Each skill names this variable
  differently (`REVIEW_DIR` for deck-review/financial-model-review/cap-table, `ANALYSIS_DIR` for market-sizing/competitive-positioning, `SIM_DIR` for ic-sim) — same role, different name per skill's convention.
- Cowork-specific: files under `$OUTPUTS_ROOT/` are write-yes,
  delete-no by default (overwrite in place works; `rm` is denied until
  the user approves a delete). Use a `/tmp` `$STAGING_DIR` (`mktemp -d`)
  for ad-hoc files — see Cowork-Specific Quirks below for the full
  pattern.

### 2. Context A — Per-Step Analytical Sub-Agent

- Dispatched by main thread via Task tool.
- Tool surface **on Claude Code and Cowork**: exactly what the agent's
  `tools:` frontmatter declares and the host registers (strict allowlist
  mode — undeclared names don't bind; declared names that the host
  doesn't register silently bind nothing). **This is a host property,
  not a property of the skill format.** A host that spawns sub-agents
  without per-spawn tool scoping — ChatGPT Work's hosted sub-agents
  "use the tools available to the parent chat" — ignores the
  declaration entirely, which turns every no-shell Context A boundary
  in these skills from an enforced allowlist into prose. Branch on the
  capability, never on the product name (see the Host-Capability
  Matrix). Our agents declare Read/Edit/Glob/Grep;
  competitive-positioning's also declares `WebSearch` for its own
  LANDSCAPE_RESEARCH/MOAT_SCORING/POSITIONING_SCORING research — it is
  the only skill where Context A makes network calls. **WebSearch
  resolves for any sub-agent that declares it, in Cowork too**
  (live-confirmed 2026-07). Keeping the other skills' Context A
  network-free is our design choice, not a platform limit.
- Role: heavy analytical work in isolated context. Produces structured
  JSON matching a producer script's input schema. Does NOT write
  canonical artifacts.
  - **Exception**: cap-table's Context A is extraction-only
    (INSTRUMENT_EXTRACTION / SPREADSHEET_STRUCTURE_DETECTION /
    ARTICLES_OF_ASSOCIATION_EXTRACTION) — cap-table math is fully
    deterministic and rule-pack-driven, so there is no
    analytical/judgment work in the math layer requiring a sub-agent.
  - **Exception**: financial-model-review's UNIT_ECONOMICS and
    RUNWAY_SCENARIOS steps are NOT dispatched to a sub-agent — those
    producers consume `inputs.json` verbatim, so the main thread
    pipes the file directly.
- **Invariant: a Context-A sub-agent never handles a VM-absolute path.** In
  Cowork hostloop a sub-agent's file tools run host-native (cwd IS the session
  outputs dir) while the main thread's shell (`mcp__workspace__bash`) runs in
  the VM; a host-side containment hook denies any gated file op
  (Read/Write/Edit/Glob/Grep) whose path is a VM-namespace
  `/sessions/<id>/mnt/…` path — **for the main thread's own file tools too**,
  not just the sub-agent's (see "Two path namespaces" below). So a dispatch
  prompt gives the sub-agent paths ONLY in forms it can reach host-native,
  chosen by where the target lives:
  - **A bundled `references/*.md`** → the literal `${CLAUDE_PLUGIN_ROOT}/skills/<skill>/references/<f>.md`
    token. It is pre-resolved (at skill-body load) to a host-readable plugin
    path — do NOT pass a `find /sessions`-discovered `$REFS` value (a VM path a
    file tool can't read). This holds for MAIN-THREAD `Read` directives as well.
  - **An artifact under `outputs/`** (a prior step's `*.json`) → a **cwd-relative
    `artifacts/…` path** from the `resolve_artifacts_root.py --agent` namespace
    (the same namespace as `OUTPUT_PATH`; build a `<WORKDIR>_AGENT` var beside
    `HANDOFF_AGENT`). The sub-agent's cwd is the outputs mount, so the relative
    read resolves; an absolute `/sessions/…` read is denied. Relative reads are
    preferred over inlining these (inlining double-pays tokens through the
    orchestrator context).
  - **Content OUTSIDE outputs** (an uploaded file, raw deck/document text) →
    **inline it** into the dispatch prompt (the main thread reads it; the
    sub-agent gets the text, not a path). This is the only content that needs
    paste-transport.

  The sub-agent's own **write** is the single Write to the agent-namespace
  `OUTPUT_PATH` (never a VM-absolute path). The stable analytical rubric a step
  needs (scoring criteria, archetype/persona definitions, checklists) is best
  kept in the **agent definition** (`agents/<skill>.md`), loaded into the
  sub-agent's context with no read at all. (A skill MAY choose the all-inline
  variant — zero sub-agent reads, every input pasted in, as `ic-sim` does — but
  the relative-read forms above are the cheaper default for under-outputs
  artifacts.)
  cap-table is the exemplar this generalizes from: its Context A extraction
  dispatch already passes document text inline and reads nothing (see
  "Cowork-Specific Quirks" below, and the per-skill "Available References"
  sections in each SKILL.md for the main-thread-vs-agent-def split).
- **Transport is file hand-off, not the message channel**: the dispatch
  prompt carries an `OUTPUT_PATH:` line (built from the skill's
  `$HANDOFF_AGENT` — the agent-namespace view of
  `$WORK_DIR/handoff/$RUN_ID/`); the sub-agent Writes its output JSON to
  that exact path and returns only a small receipt
  (`{"status": "complete", "output_path": "<echo>"}`). The payload
  leaves the model exactly once (into the Write call) — this removes
  the double-LLM-re-emission hazard of returning multi-KB JSON in the
  final message and re-typing it into a heredoc.
- Main thread gates the file with `scripts/check_handoff.py` (typed
  exits: 0 ok / 3 missing / 4 invalid JSON / 5 receipt path mismatch /
  6 receipt unparseable), then pipes it through the producer script
  (`cat "$HANDOFF_DIR/<step>_output.json" | python3 ...`) for schema
  validation + canonical persistence. Recovery is redo/repair
  re-dispatch with a bounded budget; the complete state machine lives
  in each SKILL.md's "Context A hand-off protocol" section.
- Hand-off files are a permanent per-run audit trail (raw sub-agent
  output before producer validation), never canonical artifacts:
  producers touch them only via the explicit pipe, and
  `compose_report.py` never reads `handoff/`.
- **Graceful degrade**: if the host's filesystem topology makes the
  hand-off invisible to the main thread (gate exits 3 while the agent's
  receipt correctly claims completion — again on the first corrective
  dispatch), fall back to message-channel transport for the rest of the
  run: the sub-agent returns full JSON in its final message, the main
  thread stages it to `$STAGING_DIR` and pipes the same way.

### 3. Context B — Post-Compose Coaching Sub-Agent

- Dispatched by main thread after `compose_report.py` produces
  `report.json` (with `coaching_payload`) and `report.md` (with a
  uuid-derived insertion marker).
- Tool surface: Read/Write/Glob/Grep (no Bash). The agent's ONLY write
  is its `OUTPUT_PATH` hand-off file — it never touches `report.md` or
  any canonical artifact.
- Role: Read the STAGED `coaching_payload.json` from the hand-off dir
  (the main thread writes it there; it is NOT inlined into the dispatch
  prompt); reason about outcomes from structured data; compose the
  coaching commentary; WRITE it to the `OUTPUT_PATH` hand-off file as
  **plain markdown** — a `.md` file, no JSON, no escaping — and return a
  small receipt `{"status": "complete", "output_path": ...}`. The main
  thread wraps that markdown into the JSON envelope with
  `md_to_commentary.py`, so the commentary leaves the model exactly once,
  into the Write call, and nothing has to hand-escape quotes or newlines.
- The MAIN THREAD gates the hand-off file (`check_handoff.py`), then
  inserts the commentary via the shared `scripts/insert_coaching.py`
  script, which handles the 6-state idempotency matrix, the exact-uuid
  marker replacement, and `run_id` parity verification across the
  producer artifacts deterministically (exit 0 =
  inserted/already_inserted; exit 1 = blocked with a JSON diagnostic).
- Does NOT read full `report.md` (Mitigation 2 — saves tokens). Does
  NOT edit `report.md` or any canonical artifact — its only write is the
  gated hand-off file; insertion is script-side.

## Why Inline (Not Forked Sub-Agent)

> **Corrected mechanism (2026-07, verified against the CLI v2.1.198 /
> Desktop v1.18286.0 binaries):** "Cowork has no built-in Bash/WebFetch
> at any dispatch level; subagents with a wildcard or explicit
> `mcp__workspace__*` grant can still shell and fetch via the workspace
> MCP tools. Outside Cowork, subagents can use Bash and WebFetch
> normally, including in async mode." Earlier versions of this file
> described a runtime filter that removed Bash from sub-agents — that
> framing is retracted (the mechanism is name-registration, not
> filtering); do not reintroduce it from git history.

Cowork has no built-in `Bash` tool at ANY dispatch level — main thread
included. Shell is `mcp__workspace__bash`, an MCP tool registered by
the desktop's workspace server that runs commands inside the workspace
VM. The main thread uses it transparently (ToolSearch, then call). A
sub-agent could too, if its `tools:` frontmatter declared
`mcp__workspace__bash` + `ToolSearch` — but ours deliberately don't:

- **Anti-fabrication:** the v0.4.0 incident showed sub-agents with a
  working shell recipe still improvised artifacts and fabricated
  results. The structural fix is that CANONICAL artifacts are only ever
  written by producer scripts run by the main thread; a sub-agent writes
  exactly one thing — its `OUTPUT_PATH` hand-off file, which is gated
  (`check_handoff.py`) and consumed by a producer or insert script, never
  promoted to a canonical artifact as-is. A sub-agent shell would blur
  that line for no benefit.
- **Portability:** `mcp__workspace__bash` doesn't exist in the
  standalone CLI or other hosts; the literal `Bash` name doesn't exist
  in Cowork. Read/Edit/Glob/Grep (+ WebSearch where declared) is the
  portable intersection.

So skills run inline in the main thread (where shell — under whichever
name the host registers — is available), and sub-agents are dispatched
for analytical work using tool names that resolve in every host. A
declared name the host doesn't register silently binds nothing, which
is why a skill's orchestration must never run as a forked sub-agent
that assumes literal `Bash`.

## Mitigation 1: Per-Step Analytical Isolation

Heavy analytical steps (slide reviews, checklist scoring, partner
archetype analysis, etc.) benefit from context isolation:
- Sub-agent's intermediate reasoning never reaches main-thread context.
- Allows per-step focus without polluting orchestration context.

Trade-off: each sub-agent dispatch costs a fresh context. Acceptable
because the analytical step is self-contained.

Some skills use **parallel dispatch**: ic-sim dispatches three Context A
sub-agents simultaneously (one per partner archetype) in a single
assistant turn. Market-sizing dispatches two simultaneously (one per
methodology) when methodology is "both". Competitive-positioning dispatches
two simultaneously for MOAT_SCORING + POSITIONING_SCORING.

## Mitigation 2: Trimmed Context B Coaching Context

v0.4.2 introduces structured `coaching_payload` in `report.json`.
Context B reads the payload (~5K tokens) instead of the full `report.md`
(10-30K tokens), and saves the difference per coaching dispatch. The
payload is STAGED AS A FILE in the hand-off dir and Read from there — a
required read, so a wrong path prefix fails loudly before anything is
written. It is not inlined into the dispatch prompt.

The agent composes the commentary and WRITES it to the `OUTPUT_PATH`
hand-off file as **plain markdown** (a `.md` file — no JSON, no
escaping), returning only a small
`{"status": "complete", "output_path": ...}` receipt. The main thread
gates it with `check_handoff.py --format=markdown` and wraps it via
`md_to_commentary.py`, whose `json.dumps` cannot emit malformed JSON. The main thread gates that file
(`check_handoff.py`) and inserts the commentary via the shared
`scripts/insert_coaching.py` script at a per-run uuid marker
(`<!-- COACHING_INSERTION_POINT_<8-hex> -->`) — the deterministic
mechanics (idempotency matrix, marker replacement, run_id parity) live
in the script, not in agent instructions.

## Per-Skill schema_version Divergence

Each skill's `coaching_payload` has a distinct `schema_version`:

| Skill | schema_version | Outcome model |
|---|---|---|
| deck-review | v0.4.2-deck-review | checklist (failed_items + warned_items) |
| competitive-positioning | v0.4.2-competitive-positioning | checklist (failed_items + warned_items) |
| financial-model-review | v0.4.2-financial-model-review | checklist + severity-sorted truncation |
| ic-sim | v0.4.2-ic-sim | dimension-based (dealbreakers + concerns) |
| market-sizing | v0.5.0-market-sizing | checklist (failed_items only — no warn status; `summary` carries the 4-band `overall_status` plus `all_pass`) |

The 4 checklist-using skills share a `summary` block shape with
`failed_items`/`warned_items` arrays (market-sizing's `warned_items`
is always `[]`). ic-sim is dimension-based and intentionally uses
its own schema.

## Producer-Script Contract

- stdin JSON in → schema validation → canonical artifact persistence.
- Producer scripts emit `metadata.run_id` (top of file) so
  cross-artifact `run_id` parity can be verified.
- `report.json` has NO `metadata.run_id` — it's compose-side
  aggregator output, not a producer artifact.
- Main thread pipes the gated hand-off file through the producer
  script — never trusts sub-agent JSON directly for canonical artifact
  persistence.

## Tolerant JSON Extraction Protocol

Applies to sub-agent receipts (Context A and Context B) and any
message-channel fallback (Context A, or Context B graceful-degrade).
Capture the sub-agent's final assistant message. It should be
raw JSON, but may be wrapped in fences or carry prose. Extract
tolerantly:

1. If the message is wrapped in a ` ```json ... ``` ` (or plain ` ``` ... ``` `) fence, strip the fence first.
2. Try to parse the stripped text directly as JSON.
3. If that fails, walk through the text looking for the first `{` character and try `json.JSONDecoder().raw_decode(text[i:])` — this is brace-aware and handles nested objects correctly (unlike regex, which truncates on the first `}`).
4. If extraction fails entirely, re-prompt the sub-agent with: "Your previous reply could not be parsed as JSON. Return ONLY the JSON object — no markdown fences, no prose preamble."

Context A receipts don't need this protocol applied by hand:
`check_handoff.py --receipt-json -` runs the same tolerant extraction
internally — pass the final message verbatim.

## Cowork-Specific Quirks

- **RPM cache**: plugin updates are version-keyed. Bump
  `plugin.json`'s `version` to invalidate. Sessions started before
  the bump keep their cached version.
- **Literal `Bash` doesn't resolve in sub-agent declarations**: Cowork
  registers shell as `mcp__workspace__bash`; declared names that aren't
  registered silently don't bind. Our agents' `tools:` frontmatter
  declares no shell — sub-agents *should not need* one — but this is
  **not an enforced platform invariant**: in Cowork the workspace shell
  (`mcp__workspace__bash`) is reachable to a sub-agent regardless of what
  `tools:` declares (it is a live escape hatch the platform grants, not
  something our allowlist gates). Do not rely on "sub-agents can't shell
  out" as a hard guarantee when reasoning about failure modes — rely
  instead on the Context A invariant above (zero reads, inputs inlined)
  so there is nothing for a sub-agent to need a shell for. Orchestrate
  from the main thread either way.
- **Env scrubbing across the host/VM boundary**:
  `mcp__workspace__bash` commands run inside the Linux VM with an
  allowlist-scrubbed environment — no `CLAUDE_CODE_*` variable
  survives, and hook-exported vars don't cross the boundary. The
  general rule: nothing host-side reaches the VM shell except the
  filesystem. (The invariant is about the BOUNDARY, not about hooks —
  hooks do fire on desktop-local; their exported vars just do not reach
  the VM shell. See the Host-Capability Matrix.) Never detect Cowork
  from a script via
  `$CLAUDE_CODE_IS_COWORK` — see "Runtime Detection" below.
- **`$OUTPUTS_ROOT/` is write-yes, delete-no by default**: files
  written there can be overwritten in place, but a plain `rm` is
  denied (`Operation not permitted`) until the user approves a delete.
  Design consequence: never plan a cleanup step under `outputs/`; use
  a `/tmp` `$STAGING_DIR` (writable, sandbox-reclaimed) for anything
  disposable.
- **Two path namespaces over one shared mount**: the main thread's VM
  shell and a sub-agent's file tools see the `outputs/` mount at
  DIFFERENT absolute prefixes (VM: `/sessions/<id>/mnt/outputs/...`;
  agent: the host session path). The mount itself is the only shared
  writable location — VM `/tmp` and the sandbox home are invisible to
  agent file tools. This is why `resolve_artifacts_root.py --agent`
  exists: it prints the agent-namespace root so SKILL.md can build
  `OUTPUT_PATH` lines the sub-agent's Write tool can actually reach.
  In the standalone CLI both namespaces are the same absolute path.
  **Never derive the agent namespace from the VM shell's cwd.** They are
  different processes in different namespaces: the shell can sit at the
  session root while the sub-agent's cwd is the outputs dir. Inferring one
  from the other once shipped a DOUBLED `<outputs>/mnt/outputs/artifacts/…`
  prefix that only bit the sub-agents doing no reads — a read-first agent
  self-healed and hid it. The agent-namespace root is `artifacts` on any
  Cowork session tree; a genuine VM-loop tier declares
  `$COWORK_AGENT_ARTIFACTS_ROOT` instead of being guessed at.
  **The same asymmetry that makes `OUTPUT_PATH` need `--agent` makes any
  VM-path handed to a sub-agent for READING fail identically** — a
  host-side containment hook gates Read AND Write alike, so a
  `/sessions/…`-style path denies whether the sub-agent tries to Read it
  or Write to it. `--agent` resolves the outputs ROOT, not arbitrary paths —
  but that root is exactly what an under-outputs artifact READ needs: build the
  read path in the SAME agent namespace as `OUTPUT_PATH` (a cwd-relative
  `artifacts/…` under the `--agent` root), which the sub-agent's host-native
  Read reaches. Only content OUTSIDE the outputs tree (uploads, raw document
  text) has no path form the sub-agent can reach — inline those bytes into the
  dispatch prompt. References are the third case: the literal
  `${CLAUDE_PLUGIN_ROOT}/…` token (pre-resolved to a host-readable plugin path).
  See the three-way rule in the Context A invariant above.
- **`${CLAUDE_PLUGIN_ROOT}` is unset in VM bash, on EVERY tier — and the
  plugin's mount path is not one fixed shape.** The token is substituted into
  the skill body's TEXT when the definition loads, so a host-side `Read` of it
  resolves; a VM `bash` step never inherits it, and a hardcoded expansion of it
  is a path the VM cannot see. The plugin's files ARE in the VM, bind-mounted
  under the session — but the mount path depends on how the plugin was
  installed:
  - a marketplace / local plugin → `mnt/.local-plugins/marketplaces/<marketplace>/<plugin>`
  - an **uploaded or org-remote plugin** → `mnt/.remote-plugins/plugin_<id>`,
    where the id is a stable hash of the DECLARED SOURCE (not a basename — two
    entries sharing a basename used to collide)
  So a shell step must DISCOVER the mount rather than depend on the token, which
  is what the `find /sessions/*/mnt/.*-plugins …` self-heal in Step 0 is for.
  Finding the plugin at `.remote-plugins/plugin_<id>` does NOT mean the "leave
  reference paths literal" instruction is wrong — that instruction governs the
  sub-agent's host-side `Read`, which is correct on every tier. Conflating the two
  namespaces is the trap. Keep them separate: **host-side `Read` → use the token;
  VM `bash` → discover the mount.**
- **Main-thread reference reads use the `${CLAUDE_PLUGIN_ROOT}` token with
  the Read tool — in EVERY fidelity tier, including Cowork hostloop.** In
  hostloop the main thread is the native host process, and its
  `CLAUDE_PLUGIN_ROOT` is a real host path to the staged plugin copy — the
  host-side containment hook carries an explicit exemption for it. So
  `Read ${CLAUDE_PLUGIN_ROOT}/skills/<skill>/references/…` from the main
  thread is the endorsed idiom in all tiers; do not route it through
  `mcp__workspace__bash`/`cat` as a workaround, and do not treat it as
  needing the same fix as sub-agent VM-path reads (a different failure
  class — see the Context A invariant above). Route through
  `mcp__workspace__bash` only for paths that are genuinely VM-namespace:
  `/sessions/…/uploads/…` (uploaded documents) and
  `/sessions/…/mnt/outputs/…` (dynamic artifacts under `outputs/`).
- **`STAGING_DIR` pattern for ad-hoc/scratch files**: each skill's
  SKILL.md Step 0 creates `STAGING_DIR="$(mktemp -d ...)"` — a `/tmp`
  scratch dir outside the promoted `outputs/` tree, reclaimed by the
  sandbox (never `rm` it). Used for ad-hoc scratch and for the Context
  A message-channel fallback (stage the returned JSON, then
  `cat "$STAGING_DIR/<step>_input.json" | python3 "$SCRIPTS/<producer>.py" ...`).
  Sub-agent hand-off files do NOT go here — they go to
  `$WORK_DIR/handoff/$RUN_ID/` (the audit trail; see Context A above).
  This reference documents the *rationale*; the runnable recipes stay
  inline in each SKILL.md.
- **uuid marker rationale**: Per-run uuid (`uuid4().hex[:8]`) ensures
  the exact-string marker replacement can't collide with body content.
  `insert_coaching.py` targets the EXACT uuid (not the prefix
  substring) so body-content collisions don't block delivery.
- **Sub-agent network access follows the declaration, not the
  platform**: WebSearch resolves for any sub-agent that declares it in
  `tools:` — in Cowork too (see the live confirmation in the Context A
  section above). Literal `WebFetch` doesn't exist anywhere in Cowork
  (main thread included); its replacement is
  `mcp__workspace__web_fetch`. Our design: only
  competitive-positioning's Context A declares `WebSearch`; every
  other skill researches in the main thread before dispatch and passes
  the data inline in the sub-agent prompt.
- **No localhost access from host browser**: Cowork runs agent code
  inside a local VM; the browser runs on the host outside the VM.
  Server-based tools (HTTP review viewer) don't work in Cowork —
  use the static HTML output mode instead.

## Host-Capability Matrix

Pinned to CLI v2.1.198 / Desktop (Cowork) v1.18286.0. "Other host"
covers Codex, Cursor, and similar agent harnesses running these skills.
ChatGPT Work has its own column because its sub-agents are hosted and
unscoped — see "Context A" above for what that costs.

| Capability | Cowork | Standalone CLI | ChatGPT Work | Other host |
|---|---|---|---|---|
| Shell in main thread | `mcp__workspace__bash` (transparent) | literal `Bash` | varies | varies (some shell) |
| Web fetch in main thread | `mcp__workspace__web_fetch` | literal `WebFetch` | varies | varies |
| Literal `Bash` in sub-agent declarations | no (doesn't resolve) | yes | n/a (no scoping) | varies |
| `WebSearch` in sub-agents | yes, if declared | yes, if declared | n/a (no scoping) | varies |
| Per-spawn sub-agent tool scoping | yes (declaration binds) | yes (declaration binds) | **no** — hosted sub-agents use the parent chat's tools | varies |
| Blocking structured question | `AskUserQuestion` | `AskUserQuestion` | no in-chat equivalent observed; MCP elicitation is a possible path, unconfirmed | varies |
| Sub-agent resume after completion | no (`SendMessage` omitted from the spawn tool list) | yes (`SendMessage`, ≥ ~v2.1.159) | varies | varies |
| Background tasks | disabled (`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`) | available | varies | varies |
| Hooks fire | yes on desktop-local; unverified on cloud | yes | varies | varies |
| `outputs/` delete/overwrite-by-delete | denied post-write (in-place edit works) | normal filesystem | varies | normal filesystem |

**Hooks.** Plugin-declared `SessionStart` hooks run on the desktop-local
lane — sessions carry `<session>/.claude/session-env/<uuid>/sessionstart-hook-N.sh`,
where this plugin's hook appears as its `export CLAUDE_PLUGIN_ROOT=…` line.
The cloud lane is unverified either way: a cloud task leaves no local
session directory to inspect, so treat it as unknown, not as "no".

Firing is not reach. Hook-exported variables still do not cross the
host/VM boundary, so a hook can run and its environment never reach the
shell a skill uses. **Skills must not depend on hook-exported state** —
that rule is unchanged. What changes is the reason, and it matters: a
host-side hook mechanism that never needs to cross into the VM is not
ruled out.

Two design consequences:

1. **The skills' contracts use only the intersection column**: read and
   write files, fresh one-shot sub-agent dispatch, shell in the main
   thread. Host-specific capabilities (resume, background tasks) may be
   mentioned as optimizations but are never required for correctness.
2. **Branch on the capability, never on the product name.** Check
   whether the tool is present in the current surface (e.g. "if a
   `SendMessage` tool is available…"), not "if this is Cowork". Cowork's
   resume severing is a Desktop spawn-config decision that can flip
   between builds; capability checks stay correct either way. (Existing
   precedent: deck-review's stage gate branches on `AskUserQuestion`
   availability, not host detection.)

Resume note (documentation only — no skill content depends on it): in
the standalone CLI, a completed or stopped sub-agent can be resumed
with full context via `SendMessage`. In Cowork the Task dispatch is
one-shot. Skills therefore use redo/repair re-dispatch as the baseline
recovery path everywhere; a host with resume may use it as an
optimization, gated on `SendMessage` presence.

## Runtime Detection (When a Script Must Branch)

Prefer not branching at all — the transparent-tool-name design means
most logic doesn't care which host it's on. When a script genuinely
must know, use these signals **in order** (pinned to CLI v2.1.198 /
Desktop v1.18286.0; the host-loop/VM-loop split is itself
feature-gated, and this order is robust to that flip):

1. `$CLAUDE_CODE_IS_COWORK` set → Cowork (catches VM-loop orgs and
   host-side hook contexts).
2. Filesystem signature: cwd or mounts match `/sessions/<id>/...` →
   Cowork VM shell (catches host-loop orgs, where the env var is
   scrubbed before the command reaches the VM).
3. `$CLAUDECODE == 1` → some Claude Code Bash subprocess (refine with
   `$CLAUDE_CODE_ENTRYPOINT` if CLI-vs-SDK matters).
4. Otherwise → other host; assume nothing beyond the intersection
   column.

Content-side (model branching inside a SKILL.md, not a script): the
tool surface itself — plain `Bash` vs `mcp__workspace__bash` — is the
one signal Cowork can't hide, because the substitution IS the
architecture.

Do NOT rely on: a bare `$CLAUDE_CODE_IS_COWORK` check alone in scripts
(scrubbed in VM shells — concludes "not Cowork" exactly when it IS
Cowork), `${CLAUDE_PLUGIN_ROOT}` as a location signal, `uname`, or
hook-exported sentinel vars — hooks do run on desktop-local, but their
exported vars don't cross the host/VM boundary, so the sentinel is
absent in the shell doing the detecting.

Existing precedent: `scripts/resolve_artifacts_root.py` detects by
filesystem signature (`outputs/`, `mnt/outputs/`,
`sessions/*/mnt/outputs`), not env vars — follow that pattern. If a
future script needs a runtime branch, add a shared `detect_runtime()`
helper implementing the order above rather than ad-hoc env checks.

## Per-Symptom Triage

| Symptom | Likely cause | First check |
|---|---|---|
| Sub-agent returns BLOCKED | Dispatch prompt missing required field | Check the agent body's "input keys" requirements vs. what the dispatch prompt actually inlines. |
| `check_handoff.py` exit 3 (missing/empty file) | Agent never wrote, or wrote outside the mount (fabricated/mistaken receipt) | Redo-dispatch with the one-line correction. If the receipt correctly echoes the path AND the first corrective dispatch exits 3 again → transport-visibility failure, not agent failure: degrade to message-channel for the rest of the run. |
| `check_handoff.py` exit 4 (invalid JSON) | Truncated or malformed Write | Repair-dispatch quoting the parse diagnostic verbatim — the analysis on disk survives; only serialization gets fixed. |
| `check_handoff.py` exit 5 (path mismatch) | Agent wrote somewhere else and echoed that path | Repair-dispatch stating the exact expected OUTPUT_PATH. If the claimed path is the OTHER namespace's spelling of the same file, `--agent-path` should have accepted it — check the gate invocation passes `--agent-path`. |
| `check_handoff.py` exit 6 (receipt unparseable) | Final message wasn't the receipt JSON | Redo-dispatch: "return ONLY the receipt JSON — no fences, no prose." |
| Producer script schema rejection | Hand-off file (or fallback JSON) shape doesn't match schema | Repair-dispatch with the producer's stderr verbatim; check schema in references/schemas/. |
| `metadata.run_id` mismatch | `setup_run.py` invocation order issue | Check that all producer scripts use the same `RUN_ID` (set once at Step 0, threaded through). |
| Coaching commentary missing | Compose didn't emit insertion marker | Check `report.md` for `<!-- COACHING_INSERTION_POINT_<8-hex> -->`. If absent, compose script wasn't updated to v0.4.2 spec. |
| `Operation not permitted` on `rm` | File written to `$OUTPUTS_ROOT/` (write-yes, delete-no by default) | Don't delete — overwrite in place, or put disposable files in a `/tmp` `$STAGING_DIR` instead. Hand-off files are intentionally permanent (audit trail). |
| `insert_coaching.py` exits 1 (blocked) | Marker missing/duplicated, or `run_id` parity failure across `--verify-artifact` paths | Read the JSON diagnostic on stdout — it names the failing state. Marker issues: re-run `compose_report.py --write-md` and retry. Never hand-edit `report.md`. |
| Sub-agent can't reach network | The agent's `tools:` allowlist doesn't declare `WebSearch` (strict allowlist mode — undeclared names don't bind); also note literal `WebFetch` doesn't exist in Cowork at all | Either the sub-agent's frontmatter declares `WebSearch` (competitive-positioning's Context A is the documented case), or move research to the main thread before dispatch and pass data inline in the prompt. |

## See Also

- Each skill's SKILL.md for skill-specific procedure.
- Each agent body in `agents/` for Context A and Context B per-context contracts.
- `tests/fixtures/dispatch_contracts.json` for the formal dispatch contracts.
