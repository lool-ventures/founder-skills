# founder-skills cowork-harness tests

Token-free **replay** PR gate (`.github/workflows/cowork-replay.yml`) over committed cassettes that
exercise the founder-skills skills under Claude Cowork's runtime via
[`cowork-harness`](https://github.com/yaniv-golan/cowork-harness) (**pinned to `0.10.0`** — see the note).
Recording is **live** (needs the staged agent + Docker); replay/verify are **token/agent-free** (stock CI).

> **0.10.0 note (current pin).** Cassette format is still **v6** — the upgrade forces no re-record.
> New in 0.10.0: `record` can answer gates **live** (`--decider-llm` / `--decider-dir` / `--on-unanswered`)
> for one-pass cassette authoring (see "Record" below); `verify-run` now also checks `answers:` coverage —
> a drifted `when_question`/`choose` fails in ~1s instead of on a paid record (exits `1` on answer mismatch,
> `2` if the kept run has no `events.jsonl`); `lint` **bundles its own PyYAML** (no `pip install pyyaml`) and
> flags positional `choose: first` as order-dependent (advisory); `doctor` detects the
> "macOS-Keychain-but-no-`.env`" auth trap and points you at copying the token into `./.env`.
> **Breaking — `stalled` verdict:** a run ending on an unanswered trailing question (final assistant turn
> ends with `?`, no tool call, no `AskUserQuestion`) now **FAILS** by default; opt out per scenario with
> `allow_stall: true`. None of our scenarios need it (verified by replay under 0.10.0).
> **Why an exact pin, not a `>=` floor:** pre-1.0 minors may break — a future cassette-format bump would
> replay-FAIL our committed cassettes in CI, which cannot re-record. Bump the pin in `cowork-replay.yml`
> deliberately after the ~30s token-free gate (lint + privacy + replay) goes green on the new version.
>
> **Carried forward from 0.9.0 (still in effect):** the **git-tracked file set** is the boundary for both
> the staleness hash and the sandbox mount, so a freshly re-recorded cassette passes its own staleness
> check; on a mismatch `fileSigs` names the exact changed file and `COWORK_HARNESS_DEBUG_SKILLHASH=1` dumps
> the hashed set. Never set `COWORK_HARNESS_GITSET=0` (reverts to the legacy raw-walk boundary).

Coverage: a deep **cap-table** matrix (7 cassettes across all four extraction lanes) plus a
**fleet-parity smoke** — one happy-path cassette per other skill (market-sizing, ic-sim,
competitive-positioning, deck-review, financial-model-review) proving the `resolve_artifacts_root.py`
fix lands deliverables at `outputs/artifacts/<skill>-<slug>/` and Cowork parity holds (no host-path
leak, no outputs/ delete). See `docs/internal/2026-06-18-phase1-2-fleet-cowork-plan.md`.

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

*Audit (2026-06-21):* all 11 cassettes' asserts are already parity / extraction / structural-presence
— zero deterministic-pytest duplicates. No trims needed. (The 12th, `cap-table-lane3-freeform`, follows
the same discipline: parity + hard-fact extraction asserts only.)

## Release-cadence re-record

Staleness is a **WARN** gate (CI can't re-record), so refresh on a **release cadence**, not per-PR:

```bash
export COWORK_AGENT_BINARY="$HOME/Library/Application Support/Claude/claude-code-vm/<ver>/claude"
./rerecord.sh                 # all scenarios (or: ./rerecord.sh <name> ... for a subset)
```

`rerecord.sh` needs the staged agent + Docker + the **`:2`** agent image (rebuild via
`cowork-harness doctor --tier container`). It records per-cassette (temp+`mv`, atomic), then runs the
same gates as CI scoped to what it recorded (lint, privacy with the shared allowlist, staleness,
replay). On green, review `git diff -- cassettes/` (synthetic only) and commit by name. See the
release-process note in the repo `CLAUDE.md`.

### Future: automated live lane (deferred)

The re-record treadmill exists because the staged agent ELF isn't redistributable, so the **live**
lane can't run on hosted CI — only the token-free **replay** lane does. **Trigger to revisit:** if the
cassette matrix grows past what a release-cadence manual `rerecord.sh` can sustain, stand up a
**self-hosted runner** with the staged agent to run a periodic (nightly/weekly) live re-record +
verify, turning the manual chore into always-fresh automation. **Decision today: deferred** — the
current matrix (7 cap-table cassettes + 5 smokes) doesn't justify the runner cost.

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

## Scenarios
| Scenario | Lane / mode | Proves |
|---|---|---|
| `cap-table-safe-full` | 4 (conversational) | full pipeline → deliverables + `cap_state.as_converted_totals` |
| `cap-table-extract-safe` | 1 (SAFE PDF) | extraction (cap/discount) + canonical `form` enum (P1-b/P0-c) |
| `cap-table-antihallucination` | 1 (term-sheet PDF) | blank `exclusivity_days` is NOT fabricated (P0-b) |
| `cap-table-carta` | 2 (Carta XLSX) | sheet-fingerprint mapping → instruments (P2-a) |
| `cap-table-lane3-freeform` | 3 (freeform XLSX) | freeform-grid structure detection → founders + SAFE blocks; non-mappable "Returns" tab → `derived_calculation` (role-contract) |
| `cap-table-priced-ad` | 4 (conversational) | priced round + BBWA anti-dilution (P2-b) |
| `cap-table-fast-assess` | conversational | Phase-O fast-assess routing + sentinel (P2-c) |
| `market-sizing-smoke` | conversational | resolver path + `report.json`; research-skill (cites sources, §6) |
| `ic-sim-smoke` | conversational | resolver path + `report.json`; 3 parallel partner dispatches |
| `competitive-positioning-smoke` | conversational (fixed competitors) | resolver path + `report.json`; 2 STOP gates + parallel ×2 dispatch |
| `deck-review-smoke` | paste (synthetic deck) | resolver path + `report.json`; staging-in-/tmp fix |
| `financial-model-review-smoke` | upload (Excel) | resolver path + `report.json`; 2 gates + `--static` review; staging-in-/tmp fix |

## Record (local / self-hosted only)
```bash
export COWORK_AGENT_BINARY="$HOME/Library/Application Support/Claude/claude-code-vm/<ver>/claude"
export COWORK_HARNESS_RUNS_DIR=/tmp/ct-cowork-runs        # MUST be outside the mounted plugin tree
cd cowork-tests
cowork-harness record scenarios/<name>.yaml --out cassettes/<name>.cassette.json
```
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

### Iterating asserts cheaply (0.5.0 `verify-run`)
A wrong/edited `assert:` does **not** need a live re-record. With a kept run dir (set
`COWORK_HARNESS_RUNS_DIR`), re-evaluate the scenario's asserts against it in ~1s, no agent/tokens:
```bash
cowork-harness verify-run /tmp/ct-cowork-runs/<scenario>/local_<id> scenarios/<scenario>.yaml
```
Only re-record (live) when the *run itself* must change. (Refuses rather than false-passes if a
filesystem assertion needs a torn-down work dir.)

**Answer coverage (0.10.0).** When a scenario declares `answers:`, `verify-run` now also checks that each
scripted answer still matches a gate the kept run actually fired (parsed from the run's `events.jsonl`,
which retains the offered option labels) — so a drifted `when_question` or a `choose:` naming an option the
run never offered **fails in ~1s** instead of on a paid re-record. ⚠️ This changes `verify-run`'s
exit-code contract: a run green on `assert:` can now exit **`1`** on an answer mismatch; if the scenario
declares answers but the kept run dir has no `events.jsonl`, it exits **`2`** (refuses rather than vacuously
passing). Assert-only scenarios (no `answers:`) are unaffected. Use this to validate `answers:` edits off a
kept run before committing — it's the cheap guard for the gate-phrasing-drift class of re-record flake.

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
> `agents/`) changed without a re-record. A `[stale] baseline moved …` finding **locally** is expected
> when your Cowork Desktop is ahead of the harness's shipped baseline; a hosted CI runner has no newer
> Desktop, so it doesn't fire.

## Constraints (do not break)
1. **Whole-plugin mount** — the session mounts `../../founder-skills` (the plugin root) so the rule pack +
   shared scripts are in scope. Narrowing to `skills/cap-table/` reintroduces non-determinism /
   stale-fingerprint gaps.
2. **`COWORK_HARNESS_RUNS_DIR` outside the plugin** — the ephemeral run dir must not live under
   `founder-skills/` (else the harness copies the plugin into a subdir of itself → recursive-copy
   error, and pollutes the skill hash).
3. **Synthetic data only** — cassettes are committed; never record against a real company/founder/
   cap table. The `verify-cassettes` privacy scan is the backstop, not the only guard.
