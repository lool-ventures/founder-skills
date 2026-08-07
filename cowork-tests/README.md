# founder-skills cowork-harness tests

Token-free **replay** PR gate (`.github/workflows/cowork-replay.yml`) over committed cassettes that
exercise the founder-skills skills under Claude Cowork's runtime via
[`cowork-harness`](https://github.com/yaniv-golan/cowork-harness) (**floor `1.19.0` on the `replay`
job, tracking forward within `1.x`**; see the note). Recording is **live** (needs the staged agent +
Docker); replay/verify are **token/agent-free** (stock CI).

> **Current: cowork-harness `1.19.0` (FLOOR, not pin).** A floor is applied **per CLI site**, only where
> a step depends on a version — the sites are NOT uniform and must not be bumped as a block:
>
> - **The four `version:` inputs in the `replay` job carry `^1.19.0`.** They are LINT, PRIVACY,
>   STALENESS and REPLAY — enumerate with `grep -n 'version: "' ../.github/workflows/cowork-replay.yml`
>   rather than from prose. The **email canary is not among them**: it is a bare `run:` step with no
>   `version:` input, riding the CLI the preceding Action step installed.
> - **The `skill-static-analysis` job's standalone install stays `npm i -g cowork-harness@^1.17.0`.**
>   It runs `record --dry-run` + `lint`, expands no `${ALLOW[@]}`, and uses no flag newer than 1.17.0.
>   A floor should express a requirement; that step has none. (It resolves to the newest 1.x anyway.)
>
> `^` **fails loud** below the floor and cannot cross a future `2.0`. Node **22+** as of 1.14.0 (20 is
> EOL; `doctor` fails on it).
>
> **Why 1.19.0 on the `replay` job.** The privacy gate's floor is load-bearing, not cosmetic. The
> allowlist no longer passes `--allow-host-inventory`: 1.19.0 exempts a mounted plugin's own
> `agents[]`/`skills[]` automatically (derived from the cassette's own `plugins[]`, so it applies to
> recordings made before the release — no re-record). On a 1.18.0 CLI that exemption does not exist and
> the same allowlist reds on **240 non-findings** — measured, `npx cowork-harness@1.18.0` → exactly
> 240, exit 1. Unlike previous bumps, a resolved-older CLI here does not degrade quietly; it fails
> loudly and wrongly. 1.19.0 also adds the `mutation` JSON envelope that the `--mutate` coverage
> diagnostic reads.
>
> **Why 1.17.0 and not 1.16.0.** Two independent reasons, one of which only bites the remote lane:
> `undelivered_deliverables` fired on **every** `lane: remote` run before 1.17.0 — the `presentedFiles`
> arm can never match there (no remote delivery tool is served, so the array is structurally empty), so
> a run that wrote a file still warned "never reached the user". 1.17.0 gates it behind
> `deliveryObservable()` and adds **`delivery_unobservable`**, which states the gap instead of guessing.
> Recording `market-sizing-remote-lane` below 1.17.0 freezes a warn set that asserts something false.
> Separately, `lint-skill`/`run` gained plugin **hook** findings (`hooks-json-misplaced`,
> `hook-event-unknown`, `hook-event-not-served`) — this plugin declares its `SessionStart` hook inline in
> `plugin.json`, not as a `hooks/hooks.json`, so the misplacement footgun does not apply here; verified
> clean.
>
> **1.17.0 carries NO re-record debt** (unlike the 1.14.0 trigger). Verified by diffing the pinned
> baseline across tags: `spawn.tools`, `spawn.allowedTools`, `spawn.env`, `spawn.promptTemplate`,
> `spawn.subagentPrompt`, `spawn.options` and `spawn.effortDefault` are **byte-identical** between
> `v1.16.0` and `v1.17.0`. The baseline's only additions are a `hooks` object and its comment, recorded
> — in the harness's own words — as "a DRIFT TRIPWIRE, not an emulation source", with `served: true` on
> `PreToolUse:Task` alone, which was already installed. The emulated tool surface, spawn env and system
> prompt are unchanged, so existing cassettes stay fidelity-valid.
>
> **This is the release where the floor stopped being documentary.** 1.16.0 stamps a cassette whose
> scenario carries `lane: remote` at cassette format **v11**. An older CLI does not silently mis-score
> such a cassette — it **refuses that file**, and the invocation exits non-zero. (Mechanism, measured:
> the *other* cassettes in the directory are still read and scanned; only the v11 file is refused, and
> the **exit code** is invocation-wide.) So from the moment `market-sizing-remote-lane` is recorded,
> every step that READS `cowork-tests/cassettes/` genuinely requires >=1.16.0 — `replay` and both
> `verify-cassettes` steps, which is why they no longer ride the Action's default `latest`. The stamp is
> **conditional and value-aware**: `lane: local`/omitted still writes v10, so the other 16 cassettes are
> untouched (verified: `rehash --dry-run` reports "already at v10" for all 16).
>
> Two floors that bite for their own reasons: the **`Scenario load check`** step (`record <dir>
> --dry-run`) needs >=1.14.0 now that a `lane:` scenario exists, because an older **loader** exits 2 on
> the whole directory; and its `--quiet` needs >=1.16.0 to do anything. The **`lint`** step's floor
> stays documentary — it resolves no baseline and emits no staleness.
> Do not reason about them as a way to keep CI and local in sync — they are not. Since the `1.0.0` stable release, SPEC.md §12 freezes the covered surfaces, so within `1.x`
> bumps are additive / no cassette-format change and the committed cassettes keep replaying. **On each
> new `1.x`, confirm the token-free gate is green** (`uv run pytest -m cowork`, `analyze-skill
> founder-skills/ --strict`, `lint cowork-tests/scenarios/`) — verify with a **version-confirmed** binary
> (`npm install cowork-harness@<v>` then check `--version`; `npx …@<v>` is non-deterministic and can
> silently run a stale global; and if a linked dev checkout of the harness is in the global npm tree,
> `--version` alone cannot tell it from the published package — check `readlink -f "$(which
> cowork-harness)"` lands under `$(npm root -g)/cowork-harness/`).
>
> **Re-record trigger (upstream doctrine, adopted).** Re-record on every harness **major**, *and* on any
> release — including a minor — whose changelog reports a change to the **emulated tool surface, spawn
> env, or system prompt**, regardless of whether our skills moved. Those inputs are the ones with no
> automatic staleness tripwire. `1.10.0` was the first such minor (see below), and **that debt is
> settled** — every committed cassette is at `1.12.0` or later, which necessarily carries it.
> The `1.14.0` trigger — it serves `present_files` at **hostloop**, the tier this fleet records at
> (previously `container` only), so an older recording froze a toolset one `alwaysLoad` tool short of
> production's — is **now discharged for 20 of 21 committed cassettes**. Re-measured 2026-08-06 by
> reading `environment.harnessVersion` out of every file in `cassettes/`: 3 at `1.19.0`, 3 at `1.17.0`,
> 14 at `1.16.0`, and **one** still at `1.12.0` (`market-sizing-smoke`), which is the entire remaining
> scope. The prior count here — "19 at 1.16.0, 2 still at 1.12.0 (`ic-sim-smoke`, `market-sizing-smoke`)"
> — was stale: `ic-sim-smoke` was re-recorded at `1.19.0`. **Re-derive this count after every re-record
> — it has now been wrong three times, and the instruction to re-derive it did not prevent the third.** `1.15.0` adds no re-record debt (CLI flag + notice + docs; `baselines/` and `schema/`
> byte-identical to 1.14.0), and neither does `1.17.0` (see the field-level baseline diff above).
>
> **What 1.10.0 changed for this fleet (one-liner; full story in git history).** The **sandbox tool
> surface grew** — `container`/`hostloop`/`cowork` now declare `mcp__skills__list_skills`/`suggest_skills`
> and `mcp__plugins__list_plugins`/`search_plugins`/`suggest_plugin_install`, all `alwaysLoad`. So
> `tool_available` on those families is truthful at those tiers, and every cassette recorded earlier froze
> an inventory five tools short (replay-safe — no scenario here asserts `tool_available`). Upstream's
> caveat: those tools' *description strings* are a reconstruction, so assert their **presence**, never a
> behaviour that hinges on the model choosing between them.
>
> **What 1.11.0 changed for this fleet.** No format bump (read floor stays v9), no baseline move, no new
> assertion keys, `SPEC.md` byte-identical — replay stays 16/16. Four things matter here:
> 1. **`environment.harnessVersion`** — cassettes now record the CLI that wrote them. Never backfilled,
>    so our 16 stay provenance-less until re-recorded (they carry **no `environment` block at all** —
>    that field shipped in 0.28.0). `rerecord.sh`'s floor is what guarantees every future cassette here
>    is self-describing.
> 2. **The `[note] discovery-surface` lines are EXPECTED, not a regression** — one per cassette,
>    reporting that its recorded `system/init` inventory predates the 1.10.0 discovery servers
>    (container cassettes say 19 tools, hostloop 17). Where they appear: on stderr of the HARD replay step
>    (which has no `continue-on-error`) and as `results[].notes` in the verify-cassettes envelope. Where
>    they do **not**: the replay JSON envelope (so `ok`/`--strict` are unaffected), the Action's job
>    summary (its reporter renders only `results[].staleness`), and any exit code — measured: PII lane
>    exit 0, replay 16/16 exit 0.
>    **Their shape changed in 1.12.0** — see below; they are no longer 16 `::warning::` lines.
> 3. **`lint --min-severity`** — used as `--min-severity WARN` on the CI lint step only. It mutes exactly
>    our 34 unconditional INFOs (`manifest-needs-snapshot` ×17 + `gate-needs-controlout` ×17), which the
>    static linter cannot suppress on its own. `rerecord.sh`'s `lint` keeps the default INFO floor, so the
>    advisories still surface at every re-record — when they are actionable. Trade-off: the
>    scenario-fixable `positional-choose-order` INFO would also be muted in CI if a scenario ever used a
>    positional `choose:`.
> 4. **`record` writes every cassette atomically** (same-dir temp + `rename`) — documented upstream, so
>    `rerecord.sh` no longer wraps it in its own temp+mv.
>
> **What 1.12.0 changed for this fleet.** No format bump (read floor stays v9), no new assertion keys,
> replay stays 16/16 green. Five things matter here:
> 1. **An upload-bearing scenario could not be recorded at all** before 1.12.0 — the artifact↔root
>    consistency check measured `uploads/` artifacts against the user-visible roots, which deliberately
>    exclude uploads, and threw *after* the agent run. **Five of our scenarios are upload-bearing**
>    (their `session:` declares `uploads:`): cap-table-antihallucination / -carta / -extract-safe /
>    -lane3-freeform and financial-model-review-smoke. This is why `rerecord.sh`'s floor is 1.12.0.
> 2. **The cassette *note* class moved `::warning::` → `::notice::` and now aggregates** — a directory
>    replay collapses it to one `N/M cassette(s) — <reason> [kind]` line per kind instead of one per
>    cassette. The `cassette stale:` lines are **unchanged and still `::warning::`**. Never detect
>    staleness by grepping annotation text; it is not a covered SPEC §12 surface. Parse the JSON envelope.
> 3. **Baseline moved to `desktop-1.24012.9`** (agent `2.1.219`), so `baseline: latest` resolves there and
>    our cassettes report more staleness. **Not a re-record trigger under our own rule** — verified
>    directly against the baseline files, not just the changelog: `spawn.env`, `spawn.tools` and the
>    egress allowlist are byte-identical to `1.24012.1`, and `baselines/prompts/` is unchanged. Only
>    `effortByModel` differs, additively (`claude-opus-5` added; our `claude-sonnet-4-6` entry untouched).
> 4. **`preRunOrigin` is now declared in the v10 schema** and is coupled to `no_unexpected_files`, which
>    every scenario here asserts: a cassette recorded from a degraded pre-run walk fails that assertion as
>    evidence-unavailable rather than passing vacuously. After the next record, diagnose a fresh
>    `no_unexpected_files` failure as a degraded walk before suspecting a skill.
> 5. **`save_skill` / `propose_skills` are an unmodelled surface.** Cowork declares
>    `mcp__cowork__save_skill` on a standard account; the harness declares neither tool at any tier, by
>    design (the real side effect is an authenticated upload under the operator's own credentials, and
>    `overwrite: true` can replace the skill under test). Inert for us — no skill here authors or saves
>    skills — but if one ever does, a green harness run will **not** prove the edits persist.
>
> **A cassette freezes the WHOLE scenario, not just `assert:`.** `name`, `prompt`, `session`,
> `baseline`, `fidelity`, `lane`, `skills`, `answers`, `execution`, `requires_capabilities`,
> `expect_denied` and `assert` are all frozen at record time, and a plain `replay` evaluates every one
> of them from the frozen copy — it does not read the sibling YAML. **Only `assert:`/`expect_denied:`
> can be opted back to disk** (`replay --reassert`). An edited `lane:`, `fidelity:` or `baseline:`
> reaches a replay **only by re-recording**. Two consequences worth holding onto:
>
> - Editing a scenario key and replaying does **not** test that edit. (This exact mistake produced a
>   wrong finding in our 1.14.0 adoption pass, and upstream's 1.15.0 was a documentation release
>   correcting the `assert:`-scoped framing that invited it.)
> - **An unknown TOP-LEVEL scenario key in a frozen cassette is carried but never consulted** —
>   `replay` reads that object as passthrough, so it behaves exactly as if the key were absent. A
>   cassette recorded by a newer harness therefore replays **silently** under the old semantics on a
>   stale CLI. Measured, same cassette with a frozen `lane: remote`: `✓ success` on 1.13.2 and
>   `✗ FAIL` on 1.15.0 (`user_visible_artifact` cannot hold on the remote lane) — **a verdict flip on
>   the CI path, with no signal.** This is why the version floor is load-bearing for `replay`
>   specifically: a stale install does not refuse your cassette, it may quietly return the opposite
>   verdict.
> - **Frozen ASSERTIONS are not loose — do not over-correct to "replay validates nothing".** An
>   unrecognized *assertion* key, in a cassette at or below the running CLI's format version, is a hard
>   reject: `replay: … contains unrecognized assertion(s) — they would silently drop from replay …
>   Fix the assertion, or re-record.` (exit 2). Only the top-level scenario object is passthrough.
> - The **loader** (`run`/`skill`/`record`) is the strict surface for on-disk YAML — it rejects an
>   unknown key outright (exit 2 for a file, exit 1 for a directory, naming each `✗ broken:`) — while
>   `lint` only warns (exit 0). Use `cowork-harness record <dir> --dry-run` (free, no token) to check
>   that scenarios actually load; CI runs exactly that.
> - **The v11 regime (harness 1.16.0+) — three cases, and only one of them is still dangerous.**
>   1. A `lane: remote` cassette **recorded by >=1.16.0** is stamped format **v11**: an older CLI
>      refuses it loudly and the invocation exits non-zero. Safe — this is the structural fix.
>   2. A `lane: remote` cassette **recorded by 1.14.0/1.15.0** is stamped v10 and is still **silently
>      mis-scored** by any CLI that predates `lane`. `rehash` re-stamps it. We avoid this case entirely
>      by recording on >=1.16.0 (see `rerecord.sh`'s floor).
>   3. `replay --best-effort-future-cassette` overrides the v11 refusal and **deliberately reopens**
>      case 2's hole. Never use it in automation.
> - Upstream `docs/scenario.md` and `SKILL.md` stated, in 1.15.0 only, *"A key from a newer harness
>   fails LOUD on an older CLI — it is never silently reinterpreted."* That was **true of the loader and
>   false of replay**, and was corrected in 1.16.0. Do not propagate the 1.15.0 sentence.
> - **`--assert-from` on a lane-bearing scenario:** `lane` is not covered by the drift guard until
>   1.16.0, so lane equality is the caller's responsibility. We do not use `--assert-from` anywhere —
>   keep it that way on lane-bearing scenarios until the floor is 1.16.0.
>
> **`--reassert` failures are EXPECTED right now, and CI is unaffected.** Plain `replay` (what CI runs)
> evaluates the assertions **frozen in each cassette** and is 16/16 green. `replay --reassert` re-checks the
> **on-disk** `assert:` blocks instead, and those deliberately describe the behaviour the skills have TODAY,
> which the 2026-07-07 cassettes predate. The current set, all of one class — assert-now, record-later:
>
> - `input_unmodified: 'uploads/**'` × 5 (the genuine upload lanes) — pre-0.29 cassettes captured no
>   uploads input root, so there is nothing to diff against yet.
> - `subagent_file_write: path_suffix: coaching.md` × 5 — the hand-off was
>   `coaching_commentary_output.json` when these were recorded.
> - `subagent_dispatch_healthy` × 5 — newly added; needs a fresh record to have evidence.
>
> Ratchet expectation: after the next re-record, `--reassert` should be clean. Use
> `cowork-harness replay <cassette> --reassert` (token-free) as the pre-flight BEFORE paying for a record —
> and `--reassert --write` to persist a re-validated assert block with no re-record at all, when only the
> assert block changed. `cap-table-safe-full` cannot take that path (its `answers:` drifted from the
> recording, so `--reassert` refuses it outright) and needs the paid record.
>
> **Note what `subagent_file_write` can and cannot catch.** It matches the sub-agent's RAW write path —
> the relative string from the dispatch prompt — which is byte-identical whether the prefix resolves
> correctly or doubles, because the doubling happens at RESOLUTION. No `path` / `path_suffix` form can
> detect that misroute. The guard that does is **`no_unexpected_files`**, already on every scenario: a file
> landing at `outputs/mnt/outputs/artifacts/...` matches none of the `outputs/artifacts/<dir>/**` globs and
> fails the assert.

> **The two new session knobs are deliberately left unset.** `skills.suggest_enabled` (default on) and
> `skills.proactive_suggest_enabled` (default off) resolve `knob → synced baseline gate → documented
> default`. Omitting them *is* production parity, which is the whole point of the fixture; pinning them
> would freeze our runs against a future production gate flip. Set one only to test a specific gate
> state on purpose.
>
> **`scenarios/` (18) and `cassettes/` (16) are not 1:1.** `competitive-positioning-false-positive` and
> `competitive-positioning-genuine-control` have no cassette yet (pending a live record). `rerecord.sh`
> bare refreshes only scenarios that already have one and prints what it skipped — deliberately, since
> its `xargs -P` loop aborts the whole batch if any child fails and the documented revert would discard
> every good re-record with it. Author a new cassette by name, after the live-decider flow settles its
> gates.

Coverage: a deep **cap-table** matrix (8 cassettes across all four extraction lanes) plus a
**fleet-parity smoke** — one happy-path cassette per other skill (market-sizing, ic-sim,
competitive-positioning, deck-review, financial-model-review) proving the `resolve_artifacts_root.py`
fix lands deliverables at `outputs/artifacts/<skill>-<slug>/` and Cowork parity holds (no host-path
leak, no outputs/ delete). See `docs/internal/2026-06-18-phase1-2-fleet-cowork-plan.md`.

## Why this lane exists

Read this before deciding the paid re-records aren't worth it.

Founders run these skills inside **Claude Cowork**, not the Claude Code CLI, and Cowork's runtime differs
in ways `pytest` structurally cannot observe. Every failure below shipped to real founders, was found
here, and is now held by an assertion in this directory:

| Cowork-only behaviour | What it broke | What holds it now |
|---|---|---|
| Generated HTML is served from Cowork's **own origin**, not `file:` | financial-model-review's review page fired `POST /api/feedback` at a server that isn't there. If the origin answered `200`, the founder was told their corrections were **saved** when nothing was. | `analyze-skill`'s write-back analyzer found it; the `financial-model-review-smoke` cassette's `no_lost_write_back` assert locks it in. `CLAUDE.md` records the coding rules the analyzer enforces. |
| The `outputs/` mount is **append-only** — deletes are refused | Steps that promoted a file with `mv` failed mid-pipeline | `no_delete_in_outputs` on every scenario; the skills use `cp` |
| **Host/VM split**: the agent loop and in-VM bash see different filesystems, and `${CLAUDE_PLUGIN_ROOT}` is host-side | Script paths resolved in the CLI and not in Cowork; sub-agent hand-off files landed where the orchestrator couldn't read them | `lint-skill`'s plugin-root linter, `analyze-skill`'s `/sessions` path scan, and the path-gate asserts |
| Real host paths are visible to the agent | Host paths leaked into founder-visible text | the `host-path-canary` scenario (container tier) |
| Skills narrate to a founder, not a developer | Script names, `--flags`, exit codes, `W_`/`E_` codes and step labels appeared in chat | `leak_scan.py` + `tests/test_founder_facing_leaks.py`, a **ratchet** (`BASELINE = 144`) measured against these cassettes |

The economics: replay is free and runs on every PR; recording is local, paid, and needed only at the
release cadence. What you buy with a re-record is coverage of the *current* skills — an un-refreshed
cassette still catches regressions against its own baseline, which is why the staleness gate is WARN and
not a hard failure. The leak ratchet is the clearest illustration: its baseline was measured against
cassettes recorded *before* the narration rule existed, so it can only gate "no new leaks" until a
re-record lets the number ratchet down.

## Test strategy — what cassettes are for (and aren't)

Two test layers, deliberately separated. Keeping the boundary clean is what keeps this maintainable.

- **pytest (`founder-skills/tests/`) owns deterministic correctness** — math producers, validators
  given fixed JSON, gating helpers. No LLM. Fast, exhaustive, zero re-record cost. This is the
  correctness backbone.
- **Cowork cassettes own what only they can test:** LLM-in-the-loop behavior under the real Cowork
  runtime (extraction accuracy from a real doc, gate/routing decisions, sub-agent orchestration)
  **plus sandbox parity** (artifact paths land right, no host-path leak, no `outputs/` delete). A
  cassette is a frozen snapshot of one stochastic run — its strength (regression detection) and its
  cost (it goes stale on skill / baseline / format change; re-record is paid + local-only).

Consequences for authoring:
- **Assert only what this layer uniquely covers:** parity keys (`result`, `file_exists`,
  `user_visible_artifact`, `transcript_no_host_path`, `subagent_dispatched`, `dispatch_count_max`),
  hard-fact LLM extraction (`artifact_json` on an *extracted* value), and structural presence
  (`artifact_json … exists/gt:0`). Do **not** add asserts that merely re-check deterministic producer
  math pytest already covers — that's pure re-record cost for no new signal.
- **Don't grow the matrix for correctness.** Add a cassette only for a new *runtime / LLM-behavior*
  surface. cap-table's 4 lanes are runtime-distinct (PDF-read, XLSX-openpyxl, freeform-grid,
  conversational) → one each; one smoke per other skill. Correctness variants belong in pytest.
- **Provide every field the skill will gate on, in the prompt** (e.g. founder *names*, not just
  counts). If the prompt omits something the current skill mandates, the agent raises an
  `AskUserQuestion` for it — and a re-record can then flake (see the 2026-06-22 extract-safe analysis).
- **Avoid blanket `choose: first` for gates that can't be designed away.** AskUserQuestion option
  *order* is nondeterministic, so `choose: first` can land on a dead-end option (e.g. "I'll type them
  below"), stalling the run with `result: success` but no artifact. For an unavoidable select gate,
  match the specific usable option (e.g. `choose: "Use anonymized names"`) instead of `first`.
- **Anchor-discipline rule (the decision procedure for the two bullets above).** The model paraphrases
  question text AND invents option labels run-to-run, so a `choose:` label anchor is fragile — a re-record
  flakes when the anchor matches no offered option. Therefore: **label-anchor a `choose:` ONLY for a gate
  whose choice changes an `assert:` outcome** (e.g. the scenario-type gate when a dilution/AD assert depends
  on the priced round). For **every other gate, use the global `on_unanswered: first`** — it is
  paraphrase-proof (option-1, no label to drift) — UNLESS option 1 is a known dead-end for that gate, in
  which case anchor the specific usable option. A label anchor is a liability you take on only to protect a
  specific assert; default to `first`. Validate any anchor *drop* with `verify-run` answer-coverage against
  a kept run **before** the re-record — the re-record is the only place a broken anchor otherwise surfaces.

*Audit (2026-06-21):* all 11 cassettes' asserts are already parity / extraction / structural-presence
— zero deterministic-pytest duplicates. No trims needed. (The 12th, `cap-table-lane3-freeform`, and the
13th, `cap-table-note-conversion`, follow the same discipline: parity + hard-fact extraction asserts only —
the convertible-note 7-branch *math* stays in pytest; the cassette only proves the LLM-in-the-loop path.)

**Contract asserts (adopted at the 0.24.0 pin).** On top of the parity/extraction keys above, every
scenario now carries a fleet contract surface — none of which duplicates pytest, all of which test a
*runtime* property only the cassette can:

- **Pipeline entry & routing:** `skill_triggered` (the `Skill` tool actually fired for the right skill)
  + `no_skill_triggered` negative controls on the two most collision-prone smokes (a mis-route across
  the six shared-vocabulary skills is a real usability failure with no other detector).
- **Deliverable ergonomics:** `computer_links_resolve` (every `computer://` link the founder is told to
  click resolves to a real artifact) alongside the existing `user_visible_artifact` existence check.
- **Parity contracts:** `no_delete_in_outputs` (no deliverable destroyed) and `no_unexpected_files`
  (new files stay within a per-scenario allowlist — the artifact namespace incl. `…/handoff/**`, the
  founder-context sidecar, and the promoted deliverables; the stray-file / fabricated-artifact guard,
  paired with the producer `_produced_by` stamp for the overwrite-in-place case it can't see).
- **Dispatch contract:** `subagent_tool_absent: 'Bash'` turns each agent's "No Bash required" prose
  contract into a regression test.
- **Budgets:** `questions_count_max` (usability — gates asked before value), `dispatch_count_max`
  (author-chosen — production imposes *no* Task-fan-out cap; this is an efficiency tripwire, not a
  platform mirror), and `max_turns` / `tool_calls_max`. **Budgets are generous regression ceilings, not
  SLAs** — derived from observed actuals × 1.5 and tightened only from a discovery run, never
  hand-guessed toward a target. A budget breach means "this got materially less efficient," not "it
  broke."

## Release-cadence re-record

Staleness is a **WARN** gate (CI can't re-record), so refresh on a **release cadence**, not per-PR:

```bash
./rerecord.sh                 # all scenarios (or: ./rerecord.sh <name> ... for a subset)
```

`rerecord.sh` needs Docker + both staged agent binaries (the Linux/arm64 ELF and, for hostloop, the
native Desktop host binary) + the **`:2`** agent image — it preflights all of this itself via
`cowork-harness doctor --tier hostloop` and fails loud. `COWORK_AGENT_BINARY` is an optional ELF
override (doctor sha-checks whatever resolves against the baseline). It records in a bounded parallel
pool (`COWORK_RERECORD_CONCURRENCY`, default 4; per-cassette temp+`mv`, atomic), then runs the same
gates as CI scoped to what it recorded (lint, privacy with the shared allowlist, staleness, replay),
prints a **normalized `cowork-harness diff`** per refreshed cassette (per-run noise masked — this is
the primary drift review; `git diff -- cassettes/` is the secondary synthetic-only check), and tails
`cowork-harness stats` (cross-run health) + `prune` (kept-run disk bound). On green, commit cassettes
by name. See the release-process note in the repo `CLAUDE.md`.

### Future: automated live lane (deferred)

The re-record treadmill exists because the staged agent ELF isn't redistributable, so the **live**
lane can't run on hosted CI — only the token-free **replay** lane does. **Trigger to revisit:** if the
cassette matrix grows past what a release-cadence manual `rerecord.sh` can sustain, stand up a
**self-hosted runner** with the staged agent to run a periodic (nightly/weekly) live re-record +
verify, turning the manual chore into always-fresh automation. **Decision today: deferred** — the
current matrix (8 cap-table cassettes + 5 smokes) doesn't justify the runner cost.

## Layout
- `sessions/` — repo-relative sessions: the **environment** (model, plugin mount, file `uploads:`).
  All mount the **whole** `founder-skills` plugin (`local_plugins: [../../founder-skills]`) — never a
  single `skills/<skill>/` subdir (see Constraints). Uploaded fixtures live here (`uploads:` is a
  session-only key per cowork-harness — scenarios have no upload field). `default.yaml` is shared by the
  conversational/paste scenarios; `fmr-model.yaml` adds the Excel upload for financial-model-review.
- `scenarios/` — one YAML per test: the **interaction** (prompt + scripted answers + `assert:`),
  pointing at a session via `session:`. Fleet smokes are suffixed `-smoke`.
- `fixtures/` — synthetic Lane-1 PDFs (generated by `gen_lane1_fixtures.py` from the synthetic
  `cap-table-eval` sources), the synthetic Carta XLSX, and the synthetic Excel model. **Synthetic data
  only** (Cadence / Acmecorp — fictional; no real founder data). (The deck-review smoke pastes its deck
  inline in the scenario prompt — no deck fixture file.)
- `cassettes/` — recorded cassettes, committed. The replay gate runs against these.
- `canary/` — a non-recording: `email-canary.cassette.json` carries a non-synthetic email the privacy
  gate MUST flag; CI fails if it stops tripping (locks the email tripwire). See `canary/README.md`.
  **Maintenance:** hand-bump the canary's `cassetteVersion` field at every future `MIN_SUPPORTED_CASSETTE_VERSION`
  raise (envelope-only — never re-record; MEMORY: the hand-authored PII payload is a tripwire, not a capture).
  The CI step asserts an `[email]` finding (not a bare non-zero exit), so a version-floor refusal fails LOUD
  rather than silently disabling the tripwire — but the version bump keeps it evaluated in the first place.

## Scenarios
| Scenario | Lane / mode | Proves |
|---|---|---|
| `cap-table-safe-full` | 4 (conversational) | full pipeline → deliverables + `cap_state.as_converted_totals` |
| `cap-table-extract-safe` | 1 (SAFE PDF) | extraction (cap/discount) + canonical `form` enum (P1-b/P0-c) |
| `cap-table-antihallucination` | 1 (term-sheet PDF) | blank `exclusivity_days` is NOT fabricated (P0-b) |
| `cap-table-carta` | 2 (Carta XLSX) | sheet-fingerprint mapping → instruments (P2-a) |
| `cap-table-lane3-freeform` | 3 (freeform XLSX) | freeform-grid structure detection → founders + SAFE blocks; non-mappable "Returns" tab → `derived_calculation` (role-contract) |
| `cap-table-priced-ad` | 4 (conversational) | priced round + BBWA anti-dilution (P2-b) |
| `cap-table-note-conversion` | 4 (conversational) | convertible-note conversion at a qualified financing (cap_conversion); reconstructs the note + runs `note_conversion` (LLM-in-the-loop layer; the 7-branch math is pytest) |
| `cap-table-fast-assess` | conversational | Phase-O fast-assess routing + sentinel (P2-c) |
| `cap-table-acquisition` | 4 (conversational) | Israeli→Delaware flip + priced round + SAFE + 20% acquisition consideration, all concurrent (P3-a) |
| `cap-table-carta-folder` | 2 (Carta via connected **folder**) | the read-only `folders:` mount shape (`mnt/<basename>/`) — the connected-folder discovery path no upload scenario covers |
| `host-path-canary` | container-tier canary | keeps `transcript_no_host_path` exercised at the tier where a host path IS a regression (the `cowork` fleet drops it — hostloop shows host paths by design) |
| `market-sizing-smoke` | conversational | resolver path + `report.json`; research-skill (cites sources, §6) |
| `ic-sim-smoke` | conversational | resolver path + `report.json`; 3 parallel partner dispatches |
| `competitive-positioning-smoke` | conversational (fixed competitors) | resolver path + `report.json`; 2 STOP gates + parallel ×2 dispatch |
| `deck-review-smoke` | paste (synthetic deck) | resolver path + `report.json`; staging-in-/tmp fix |
| `financial-model-review-smoke` | upload (Excel) | resolver path + `report.json`; 2 gates + `--static` review; staging-in-/tmp fix |

## Record (local / self-hosted only)
```bash
cd cowork-tests            # record finds .cowork-redact.json via cwd — record from THIS dir
cowork-harness record scenarios/<name>.yaml --out cassettes/<name>.cassette.json
```
Runs land at the harness default runs root (`~/.cowork-harness/runs`) so every record appends to the
cross-run `index.jsonl` that `cowork-harness stats` reads. If you override `COWORK_HARNESS_RUNS_DIR`,
it MUST be outside the mounted plugin tree (rerecord.sh guards this).

**Record-time redaction (`.cowork-redact.json`).** Hostloop recordings contain real host paths in
model-visible text by design; the redaction policy in this dir (generated by
`cowork-harness init-redact`, tailored patterns: machine-specific path prefixes stopping before
`/mnt/` so replay's structural-marker resolution still works, plus a generic email rule) strips them
at record time. Redaction is **verdict-preserving**: `record` replays the cassette before/after and
refuses to write if redaction flips an assert or destroys a `computer://` link. It also preflights an
empty/malformed policy *before* the agent spawns at a host-path-bearing tier. `--no-redact` exists
for known-synthetic debugging records only. The `verify-cassettes` privacy scan (`path` class) is the
after-the-fact net — a `/Users/...` in a committed cassette fails the hard gate either way.
**Authoring gates without the discovery dance (0.10.0).** Pre-scripting every `answers:` entry and then
burning paid records when option labels drift run-to-run is the old pain. Instead, let the recorder answer
gates **live in one pass**: `record scenarios/<name>.yaml --decider-llm --intent "<one line>"` (a model
answers) or `--decider-dir <fresh-dir>` (you answer in-band via the `gates` / `answer` subcommands). The
cassette still **replays deterministically**, but is stamped `authoring.nonDeterministic` (+ a "re-record
may drift" warning). For a *committed* cassette, then lock the chosen answers into the scenario's `answers:`
(run `verify-run` to confirm they still match the run's gates, ~1s) and do a final **scripted** `record` so
it stays reproducible via `rerecord.sh` without a decider. `--on-unanswered first` auto-picks option 1 for
any unscripted gate — use sparingly (option order is nondeterministic, so it can dead-end). Note:
`--decider-*` is rejected with `--rerecord-stale` and with a directory batch; and `--allow-failing` only
relaxes the post-run verdict — it does **not** salvage an unanswered gate.

**Agent image (live lane):** rebuild the container agent image to `:2` before recording — run
the build command `cowork-harness doctor --tier container` prints. Image `:2` ships the doc stack
(openpyxl etc.) the xlsx/pdf skills exercise; a stale `:1` can mis-record. (Replay/CI never builds
the image.) Re-recording under 0.9.0 rewrites cassettes to format **v6** and — thanks to the
git-tracked boundary — produces a cassette that passes its own staleness check (no residual drift).
Re-record after a change to the recorded skill's `SKILL.md` / its `scripts/` / `references/` / rules.
**Staleness scope (0.5.0):** each scenario declares `skills: [<name>]`, so the staleness hash covers that
skill's `skills/<name>/` dir **plus the plugin's shared roots** — editing a *different* skill no longer
re-stales this cassette. Shared `scripts/`, `references/`, **and the per-skill `agents/<skill>.md`** (they
live in the top-level `agents/` root, not under `skills/`) DO re-stale the whole fleet (over-stale, the
safe direction). `founder-skills/tests/` is dropped via `founder-skills/.cowork-hashignore` (pytest is not
runtime). The CI staleness gate is **warn-not-fail** (CI is replay-only and can't re-record).

**`--rerecord-stale` caveat:** in 0.6.0 it re-records **from the on-disk `scenarios/<name>.yaml`** when
present (falling back to the cassette's embedded snapshot with a warning) — so it now respects `skills:`
edits. To be explicit, you can still re-record straight from the YAML (`record scenarios/<name>.yaml ...`).

**Large (truncated) artifacts (≥ 0.7.1 fix, carried in 0.8.0):** artifacts over the 64 KiB inline cap
are recorded hash-only (manifest entry: `path` + `bytes` + `sha256`, body not inlined). `file_exists` /
`user_visible_artifact` **pass from that manifest** (existence is metadata) — so we keep the rich
existence/promotion assertions on big HTML deliverables (e.g. `…_Cap_Table_Explorer.html`,
`review.html`) without committing their bodies. (0.7.0 had a regression that *failed* these; the floor was
≥ 0.7.1 and is now ≥ 0.9.0.) `artifact_json` still needs an inlined body, so assert **content** on the
small JSON producers and **existence** on the big rendered deliverables. 0.7.x+ also redacts base64
artifact bodies wholesale (`[REDACTED:base64]`) — fine here since we never assert base64 content. Always
record with the pinned harness (the manifest must be present); **0.9.0 records the v6 hash format**
(pre-v6 cassettes report "older hash format — re-record"; re-recording rewrites them to v6).

**Diagnosing a failed live record:** if `record` errors fast with an empty `agent.stderr.log` (e.g. a
missing model token — the in-Docker agent cannot read the macOS Keychain), check the run's
`events.jsonl` for a structured `{"type":"infra_error",...}` entry (0.7.0). Auth needs
`CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY` in the record environment.

### Iterating asserts cheaply (`replay --reassert` first; `verify-run` with a kept run)
A wrong/edited `assert:` does **not** need a live re-record. Two token-free options, cheapest first:

- **No kept run needed.** If only the `assert:` block changed (not `prompt`/`answers`/
  `fidelity`/`skills`/`baseline`), re-check straight against the already-committed cassette:
  ```bash
  cowork-harness replay cassettes/<scenario>.cassette.json --reassert
  ```
  This hard-fails on recording-shaping drift (prompt/baseline/fidelity/answers/skills, and skill
  content when a fingerprint exists) rather than false-passing, and warns on on-disk assert keys that
  can't be evaluated on replay (filesystem/gate/egress — same replay-class limits as any other
  replay). Reach for this first — but know its two edges: (1) it validates **removals and edits** of
  evaluable keys; an **added** key the old cassette holds no evidence for (e.g. `skill_triggered` on
  a pre-0.22 recording, `no_unexpected_files` without `preRunPaths`) fails evidence-unavailable —
  never vacuously passes — so additions are really validated by the next re-record; (2) the
  **session** (model / data mounts / discovery) is NOT drift-checked, so a model change between
  record and re-assert goes undetected — re-record if the session changed.
- **With a kept run dir** (set `COWORK_HARNESS_RUNS_DIR`), re-evaluate the scenario's asserts against
  it in ~1s, no agent/tokens:
  ```bash
  cowork-harness verify-run /tmp/ct-cowork-runs/<scenario>/local_<id> scenarios/<scenario>.yaml
  ```
  Needed when you also want to validate `answers:` coverage against real fired gates (see below), or
  when checking a filesystem assertion needs the actual on-disk run output.

Only re-record (live) when the *run itself* must change. (Both refuse rather than false-pass if a
filesystem assertion needs a torn-down work dir.)

**Answer coverage (0.10.0).** When a scenario declares `answers:`, `verify-run` now also checks that each
scripted answer still matches a gate the kept run actually fired (parsed from the run's `events.jsonl`,
which retains the offered option labels) — so a drifted `when_question` or a `choose:` naming an option the
run never offered **fails in ~1s** instead of on a paid re-record. ⚠️ This changes `verify-run`'s
exit-code contract: a run green on `assert:` can now exit **`1`** on an answer mismatch; if the scenario
declares answers but the kept run dir has no `events.jsonl`, it exits **`2`** (refuses rather than vacuously
passing). Assert-only scenarios (no `answers:`) are unaffected. Use this to validate `answers:` edits off a
kept run before committing — it's the cheap guard for the gate-phrasing-drift class of re-record flake.
**0.12.0 adds a second exit-`2` trigger:** answer-coverage also refuses ("the kept run predates the current
skill") when the skill *source* changed since the run was recorded — so verifying a freshly edited skill
against an old kept run fails loud instead of false-greening against outdated gates. Re-record (or verify
against a run captured after the edit) to clear it.

## Authoring a new scenario

The command-first path from idea to committed cassette. The generic recipes live in the
cowork-harness skill's `references/task-recipes.md` (invoke the `cowork-harness` skill to surface
them); this is the founder-skills-specific glue.

1. **Draft the interaction, no scenario file yet.** `cowork-harness chat ../founder-skills` (multi-turn)
   or `cowork-harness skill ../founder-skills "<prompt>"` (one-shot). **Landmine:** a brand-new skill
   file that is entirely git-untracked hard-fails (`BoundaryError`, exit 3) — `git add` it first (the
   mount boundary is the git-tracked set).
2. **First structured run, kept.** Write a lint-clean scaffold (`python3 <harness>/scripts/scenario.py
   scaffold …` or copy a sibling), then `cowork-harness run scenarios/<name>.yaml --keep`. Answer any
   not-yet-scripted gates live with `--decider-llm --intent "<one line>"` (a model answers) or
   `--decider-dir <fresh-dir>` (you answer in-band via `gates`/`answer`).
3. **Discover the actuals off the kept run — no re-pay.** `cowork-harness trace <run-dir> --view
   questions` (gate labels for `answers:` + `questions_count_max`), `--view dispatches`
   (`dispatch_count_max`), `--view tools`; `cowork-harness inspect <run-dir>` (artifact tree →
   `no_unexpected_files` allowlist + `file_exists` paths). The envelope's `skillsInvoked[]` fixes the
   `skill_triggered` id; `usage.turns` + `toolCounts` seed the `max_turns`/`tool_calls_max` budgets
   (observed × 1.5).
4. **Validate answers cheaply.** `cowork-harness decide --answer "<rx>=<label>" --question "<label>"`
   (~2 s, no run) and `cowork-harness verify-run <kept-run> scenarios/<name>.yaml` (~1 s; also checks
   `answers:` coverage against actually-fired gates). Follow the **anchor-discipline rule** above:
   label-anchor a `choose:` only for a gate whose choice drives an `assert:`; otherwise
   `on_unanswered: first`.
5. **Record scripted for the committed cassette.** `./rerecord.sh <name>` (subset mode) — records at
   hostloop with redaction, then runs the CI gates scoped to what it recorded and prints the normalized
   `diff`. Review the diff (synthetic only), then commit by name.

### hostloop posture (why the host-path plumbing looks the way it does)

The fleet's `fidelity: cowork` scenarios resolve to **native hostloop** (the baseline host-loop gate is
force-on): the agent loop runs as a native macOS process, and only bash/web_fetch route into a Docker
sidecar. Three consequences shape this suite:

- **Real host paths in model-visible text are expected** there, so `transcript_no_host_path` is *not*
  asserted on the `cowork` scenarios — the leak class lives on in the container-tier `host-path-canary`
  scenario, plus the privacy scan's `path` class over every committed cassette.
- **Record-time redaction is mandatory** — `.cowork-redact.json` (in this dir, from `init-redact`)
  strips host paths at the source; `record` refuses to write a cassette whose asserts or `computer://`
  links redaction broke, and preflights an empty policy before spending.
- **`allow_host_writes` is not needed** — our sessions mount `uploads:` and read-only `folders:` (mode
  `r`) only; a writable connected folder at hostloop would be the one case that requires it.

### Debugging a misbehaving skill (`trace` + `result.json`)

Every `record`/`run` leaves a **kept run dir** under `~/.cowork-harness/runs/<scenario>/<id>/`
(the harness default runs root — see `rerecord.sh`). It holds the whole story. As of 1.7.0 the
per-turn artifacts — `result.json` (the `RunResult`), `run.jsonl`, `trace.json`, `resources.jsonl` —
live under `turns/<N>/` (`turns/1/` for a single-turn `run`/`skill`); the root-level `result.json`
compat copy was **removed** (a pre-layout run dir is now refused by name — convert it with
`cowork-harness migrate-run-dir`). The cumulative streams (`events.jsonl`, `timeline.jsonl`,
`control-out.jsonl`) and the `work/` tree stay at the root, so `trace` — which derives its views from
`events.jsonl` — still reads any of it **locally — no Docker, no tokens, no re-record** — so you
can dig into a run (even one still being written, once its scenario has frozen) without spending
anything. This is our first stop when a scenario false-greens, flakes a budget, or a skill just does
something surprising.

```bash
cowork-harness trace <run-dir> --view dispatches       # sub-agent tree: prompt / output / model per node
cowork-harness trace <run-dir> --view questions        # gate lifecycle: exact question text + option set + chosen answer
cowork-harness trace <run-dir> --view tool-durations   # per-tool call-count + wall time (where the turns go)
cowork-harness trace <run-dir> --view tools --output-format json   # every tool call/result row (filter resultStatus=="error")
```

Symptom → where to look (fields are on `turns/<N>/result.json` — `turns/1/` for a single-turn run, since 1.7.0 removed the root compat copy; 0.27.0 enriched most of them):

| Symptom | Look at |
|---|---|
| `subagent_dispatched` / `dispatch_count_max` won't match | `--view dispatches` — prints each node's **prompt, output, model** (what we reverse-engineered by hand for ic-sim) |
| A scripted `choose:` matches no option (gotcha #15) | `--view questions` or `decisions[].questions` — the **exact** option labels + descriptions the model offered |
| A budget (`max_turns`/`tool_calls_max`) flakes — where do the turns go? | `--view tool-durations` + `toolDurations` / `redundantToolCalls` (repeated identical `{name,args}` = wasted work) |
| Green run, but a producer script silently errored-then-recovered | `toolErrors` rollup (per-tool `{calls, errors}`) — invisible in a pass, a real reliability smell |
| A deliverable landed in the wrong place | `workspaceFiles[]` — every user-visible file classified `output`/`mount`/`input`, with `bytes` + `sha256` |
| Which model ran / token + cache cost | `models`, `modelUsage` (per-model tokens/cost/**cacheRead**), the `trace` cache-ratio footer |
| A `record` froze as a bare `error` | `errorSource` (spawn/protocol/exit/agent/result/no_result/timeout) + `resultSubtype` + `stderrLogPath` |
| A research skill's `web_fetch` was denied | the `egress` detail (method/path/port/bytes + deny reason) |

**Worked example (real, from a `cap-table-carta-folder` v9 record).** `--view tool-durations` showed
`Agent ×1 = 35.3s` (the extraction sub-agent dominates wall time) and `mcp__workspace__bash ×30`; the
`toolErrors` rollup flagged **5 of those 30 bash calls errored** inside a *passing* run. `--view tools
--output-format json` (filtering `resultStatus=="error"`) showed all five were **script-path-discovery
probes** — the skill hunting for its plugin `scripts/` dir across candidate paths and 404-ing the misses
before the hit. It's fleet-wide (2–5 per cap-table run, worst on the connected-folder mount) — benign to
correctness but a real efficiency smell, and concrete evidence for the artifacts-root-resolution
robustness item. None of this is visible in a green replay; the trace surfaced it in ~3 local commands.

> `tasks[]` is populated too — the cap-table skill drives `TaskCreate`/`TaskUpdate` for its step plan
> (18 tool calls in that run), so `--view tool-durations` and the `tasks[]` field both reflect real
> orchestration, not just the agent's own bookkeeping.

## Replay (CI / token-free)
```bash
cowork-harness replay cassettes/                 # replay every *.cassette.json (0.4.0 dir mode)
cowork-harness lint scenarios/                   # no-silent-false-green (0.9.0: accepts a directory)
# Privacy gate (canonical allowlist is in .github/workflows/cowork-replay.yml). The real PII guard is
# synthetic-only recording (every subject is fictional — Cadence/Acmecorp). Given that, using 0.5.0's
# CLASS-SCOPED allows (an allow can't bleed across classes): currency via --allow; the DOMAIN class
# allowed wholesale via --allow-domain (research skills cite 150+ public domains; non-PII); and only
# SYNTHETIC email domains via --allow-email (acmecorp.com, RFC-2606 example.com) — any OTHER email still
# FAILS (the live PII tripwire). Decision 2026-06-18; see the workflow comment.
source privacy-allowlist.sh   # canonical allowlist — single source of truth (also sourced by the workflow + rerecord.sh)
cowork-harness verify-cassettes cassettes/ --skip-staleness "${ALLOW[@]}"
```

> **Staleness** runs as a **separate `--skip-privacy` step under `continue-on-error: true`** (warn, not
> fail) — the **privacy** step (`--skip-staleness`) is the hard gate. Warn (not hard) because CI is
> replay-only and cannot re-record, so a hard gate would block every skill PR on a manual local re-record.
> With 0.5.0 per-skill scoping (`skills: [<name>]`) the signal is now **precise**: a `[stale] skill/plugin
> dir contents changed` finding means *that skill's* dir (or a shared root — `scripts/`, `references/`,
> `agents/`) changed without a re-record. A `[stale] baseline moved …` finding fires whenever the cassette's
> recorded baseline is behind the **harness's shipped baseline constant** — the harness carries that
> constant, it does **not** read the local Cowork Desktop, so this fires identically on CI and locally. After
> a harness bump that moves the baseline (e.g. 0.12.0: `1.14271.0 → 1.15200.0`) every committed cassette
> reads `[stale] baseline moved …` on the WARN lane until the next release-cadence `rerecord.sh`; because the
> lane is `continue-on-error`, it does not fail the PR gate.

## Constraints (do not break)
1. **Whole-plugin mount** — the session mounts `../../founder-skills` (the plugin root) so the rule pack +
   shared scripts are in scope. Narrowing to `skills/cap-table/` reintroduces non-determinism /
   stale-fingerprint gaps.
2. **`COWORK_HARNESS_RUNS_DIR` outside the plugin** — the ephemeral run dir must not live under
   `founder-skills/` (else the harness copies the plugin into a subdir of itself → recursive-copy
   error, and pollutes the skill hash).
3. **Synthetic data only** — cassettes are committed; never record against a real company/founder/
   cap table. The `verify-cassettes` privacy scan is the backstop, not the only guard.
