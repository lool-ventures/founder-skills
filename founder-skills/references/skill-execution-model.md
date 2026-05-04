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
- Tool surface: full Bash + Task + Read/Edit/Write/Glob/Grep.
- Role: orchestrate the pipeline. Calls producer scripts via Bash.
  Dispatches sub-agents via Task tool for analytical work.
- Cowork-specific: `$OUTPUTS_ROOT/` is read-only post-write. Use
  `$REVIEW_DIR/.staging/` for ad-hoc files.

### 2. Context A — Per-Step Analytical Sub-Agent

- Dispatched by main thread via Task tool.
- Tool surface: Read/Edit/Glob/Grep ONLY (Cowork strips Bash from
  sub-agents at runtime; we work within that constraint).
- Role: heavy analytical work in isolated context. Returns structured
  JSON matching a producer script's input schema. Does NOT write
  canonical artifacts.
- Main thread pipes the JSON output through the producer script
  (Bash-mediated `cat | python3 ...`) for schema validation +
  canonical persistence.

### 3. Context B — Post-Compose Coaching Sub-Agent

- Dispatched by main thread after `compose_report.py` produces
  `report.json` (with `coaching_payload`) and `report.md` (with a
  uuid-derived insertion marker).
- Tool surface: Read/Edit/Grep (no Bash).
- Role: read `coaching_payload` from dispatch prompt; reason about
  outcomes from structured data; insert `## Coaching Commentary`
  via Edit replacing the uuid marker; verify all canonical artifacts
  via Grep `run_id`; return success payload.
- Does NOT read full `report.md` (Mitigation 2 — saves tokens).

## Why Inline (Not Forked Sub-Agent)

Cowork's sub-agent dispatch path filters tools at runtime — Bash is
stripped from any sub-agent's tool set, regardless of the agent's
declared `tools:` frontmatter. This is a platform-level behavior we
work around.

If a skill's orchestration tries to run as a sub-agent (e.g., user
invokes the agent directly instead of the skill), it can't run
producer scripts because Bash is unavailable. So skills run inline
in the main thread. Sub-agents are dispatched only for tasks that
fit Cowork's sub-agent allowlist (Read/Edit/Glob/Grep) — analytical
work and coaching dispatch.

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
Context B reads payload inline from dispatch prompt (~5K tokens)
instead of full `report.md` (10-30K tokens). Saves the difference
per coaching dispatch.

The agent uses Edit to insert `## Coaching Commentary` at a per-run
uuid marker (`<!-- COACHING_INSERTION_POINT_<8-hex> -->`) — no full
file Read needed.

## Per-Skill schema_version Divergence

Each skill's `coaching_payload` has a distinct `schema_version`:

| Skill | schema_version | Outcome model |
|---|---|---|
| deck-review | v0.4.2-deck-review | checklist (failed_items + warned_items) |
| competitive-positioning | v0.4.2-competitive-positioning | checklist (failed_items + warned_items) |
| financial-model-review | v0.4.2-financial-model-review | checklist + severity-sorted truncation |
| ic-sim | v0.4.2-ic-sim | dimension-based (dealbreakers + concerns) |
| market-sizing | v0.4.2-market-sizing | checklist (failed_items only — no warn status) |

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
- Main thread pipes sub-agent output through producer script — never
  trusts sub-agent JSON directly for canonical artifact persistence.

## Tolerant JSON Extraction Protocol (Context A)

After dispatching a Context A sub-agent, capture its final assistant message.
The sub-agent should return raw JSON, but may wrap it in fences or add prose.
Extract JSON tolerantly:

1. If the message is wrapped in a ` ```json ... ``` ` (or plain ` ``` ... ``` `) fence, strip the fence first.
2. Try to parse the stripped text directly as JSON.
3. If that fails, walk through the text looking for the first `{` character and try `json.JSONDecoder().raw_decode(text[i:])` — this is brace-aware and handles nested objects correctly (unlike regex, which truncates on the first `}`).
4. If extraction fails entirely, re-prompt the sub-agent with: "Your previous reply could not be parsed as JSON. Return ONLY the JSON object — no markdown fences, no prose preamble."

## Cowork-Specific Quirks

- **RPM cache**: plugin updates are version-keyed. Bump
  `plugin.json`'s `version` to invalidate. Sessions started before
  the bump keep their cached version.
- **Sub-agent allowlist filter strips Bash**: every sub-agent
  dispatched in Cowork has Bash removed at runtime, regardless of
  declared tools. Design skills to orchestrate from main thread.
- **`$OUTPUTS_ROOT/` is read-only post-write**: any file written
  there can't be deleted (`Operation not permitted`). Use
  `$REVIEW_DIR/.staging/` (writable mount) for ad-hoc files.
- **uuid marker rationale**: Per-run uuid (`uuid4().hex[:8]`) ensures
  Context B's exact-string Edit can't collide with body content.
  The agent's post-Edit Grep targets the EXACT uuid (not the prefix
  substring) so body-content collisions don't block delivery.
- **WebFetch/WebSearch unavailable in sub-agents**: network calls must
  be made in the main thread before dispatch. Pass research data
  inline in the sub-agent prompt.
- **No localhost access from host browser**: Cowork runs agent code
  inside a local VM; the browser runs on the host outside the VM.
  Server-based tools (HTTP review viewer) don't work in Cowork —
  use the static HTML output mode instead.

## Per-Symptom Triage

| Symptom | Likely cause | First check |
|---|---|---|
| Sub-agent returns BLOCKED | Dispatch prompt missing required field | Check the agent body's "input keys" requirements vs. what the dispatch prompt actually inlines. |
| Producer script schema rejection | Sub-agent JSON shape doesn't match schema | Use tolerant extraction protocol above; check schema in references/schemas/. |
| `metadata.run_id` mismatch | `setup_run.py` invocation order issue | Check that all producer scripts use the same `RUN_ID` (set once at Step 0, threaded through). |
| Coaching commentary missing | Compose didn't emit insertion marker | Check `report.md` for `<!-- COACHING_INSERTION_POINT_<8-hex> -->`. If absent, compose script wasn't updated to v0.4.2 spec. |
| `Operation not permitted` on `rm` | File written to `$OUTPUTS_ROOT/` | Move interim file to `$REVIEW_DIR/.staging/`. |
| Context B agent blocks every dispatch with collision | Agent grepping prefix substring instead of exact uuid | Verify agent's Grep target is `coaching_payload.insertion_marker` (full string), NOT `<!-- COACHING_INSERTION_POINT_`. |
| Sub-agent can't reach network (WebFetch fails) | Cowork strips WebFetch from sub-agent tool set | Move WebFetch/WebSearch calls to main thread before dispatch; pass data inline in prompt. |

## See Also

- Each skill's SKILL.md for skill-specific procedure.
- Each agent body in `agents/` for Context A and Context B per-context contracts.
- `tests/fixtures/dispatch_contracts.json` for the formal dispatch contracts.
