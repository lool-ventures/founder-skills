#!/usr/bin/env bash
# Batch re-record + verify the founder-skills cowork cassettes.
# LIVE lane: needs the staged Cowork agent binaries + Docker + tokens (paid, local/self-hosted only).
# Usage: cowork-tests/rerecord.sh [scenario-name ...]   # no args = every scenario
#
# Recording posture notes (read before the first record on a fresh setup):
#   * fidelity: cowork resolves to NATIVE HOSTLOOP (the baseline's host-loop gate is force-on): the
#     agent loop runs as a native macOS process (the staged Desktop `claude-code/<ver>/claude.app`
#     binary); only bash/web_fetch route into the Docker sidecar. Recordings therefore contain real
#     host paths unless redacted — the .cowork-redact.json policy IN THIS DIR handles that at record
#     time (record refuses to write a cassette whose asserts or computer:// links redaction broke).
#     `--no-redact` exists for known-synthetic debugging records only.
#   * `doctor --tier hostloop` (preflighted below) validates BOTH staged binaries: the Linux/arm64
#     ELF (claude-code-vm/<ver>/claude, sha-checked vs the baseline) and the native host binary the
#     hostloop agent loop actually spawns. COWORK_AGENT_BINARY optionally overrides the ELF.
#   * Watch for H3 stalledOnQuestion on question-terminal flows: add `- allow_stall: true` to the
#     scenario ONLY where the question-terminal is intended AND the deliverable is independently
#     asserted (cap-table-antihallucination already carries it).
#   * Re-record drift review: this script prints a NORMALIZED `cowork-harness diff` per refreshed
#     cassette (per-run noise masked) — that is the primary review; `git diff -- cassettes/` remains
#     the secondary synthetic-only check. Gate-answer drift on the authoring.nonDeterministic
#     cap-table cassettes is ordinary model nondeterminism.
set -euo pipefail
cd "$(dirname "$0")"   # -> cowork-tests/ (also where record finds .cowork-redact.json via cwd)

# --- preflight (fail loud; never fake a pass) ---
command -v cowork-harness >/dev/null || { echo "FATAL: cowork-harness not on PATH"; exit 1; }
# Normalize: extract bare semver even if the CLI ever prefixes its --version output.
# `|| true`: under `set -euo pipefail`, BSD/macOS grep exits 1 on no-match and would abort the
# substitution BEFORE the explicit guard below — keep the guard reachable (fail loud, not silent).
ver="$(cowork-harness --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
[ -n "$ver" ] || { echo "FATAL: could not parse cowork-harness version"; exit 1; }
echo "cowork-harness $ver"
# FLOOR: >=3.2.0 with no upper bound. Recording is the one operation where the harness version is
#   THIS HEADER WAS ONE MINOR BEHIND THE GATE when 2.3.0 was adopted (header said 2.1.0, gate required
#   2.2) — the exact drift the next paragraph warns about, sitting unfixed in the file that warns about
#   it. If you are here to change the floor, change all FOUR sites: this header, the numeric gate, its
#   FATAL message, and `_RECORDING_FLOOR` in founder-skills/tests/test_cowork_harness_floors.py.
#   * 3.2.0 is required because 3.1.0 STAMPS A RECORD-TIME FIELD NO LATER RUN CAN BACKFILL — the
#     `environment.model` block in `schema/cassette.v12.json`: the model the recording actually ran
#     (`id`, from what the agent reported, so it survives a mid-run fallback) plus where it came from
#     (`source`). Same class as the 1.11.0 `environment.harnessVersion` floor below: an older CLI
#     records a permanently provenance-less cassette. 3.1.0 also WIDENS THE SESSION FINGERPRINT to
#     cover the pinned `model:`, so a pre-coverage cassette can no longer distinguish "the field was
#     never covered" from "the pin changed since record".
#     MEASURED 2026-09-01, same corpus and allowlist, the two CLIs side by side: `verify-cassettes`
#     goes 60 -> 70 lines from 3.0.0 to 3.2.0, the delta being exactly ten
#     `[note] session-fingerprint: predates \`model\` coverage ... Re-record to adopt it.` lines, one
#     per cassette. (CI is unaffected: its privacy step passes `--skip-staleness
#     --skip-scenario-drift`, measured rc=0 / "10 cassette(s) clean" / 0 notes.)
#     WHY THIS IS A FLOOR AND NOT A SHRUG: the next re-record is a FULL PAID BATCH already owed for
#     baseline staleness. Recording it below 3.1.0 would buy ten cassettes that cannot say which model
#     produced them and that CI's own gate flags on sight — and `rehash` migrates hash FORMATS, not
#     fingerprint SHAPE, so it is not repairable after the fact. 3.2.0 rather than 3.1.0 because
#     nothing wants a 3.1.0-only recording and it keeps the floor level with the CI pin (they were
#     already equal at 3.0.0 — equal VALUES, still separate postures).
#     3.2.0 itself adds NO fidelity debt: `git diff --name-only v3.0.0..v3.2.0 -- baselines/` is EMPTY
#     and so is the same diff over `src/{runtime,hostloop,staging,agent,egress,sync}/`; `CASSETTE_VERSION`
#     stays 12, `MIN_SUPPORTED` stays 9, default baseline stays `desktop-1.40609.0`. Its changes are
#     exit codes, a new `enum-value-invalid` lint ERROR (zero findings on our 35, non-vacuity probed),
#     and docs. Full analysis: docs/internal/2026-09-01-cowork-harness-3.2.0-adoption-plan.md.
#     A WARNING ABOUT HOW THIS WAS ALMOST MISSED: the first pass concluded "no re-record debt" from a
#     prefix-scoped diff (`src/{runtime,hostloop,...}`) that structurally could not see `src/run/` —
#     where `cassette.ts` (+261/-78) and the new `model-provenance.ts` live. Diff `src/` and `schema/`
#     WHOLE and account for every file; a pre-classified prefix list is a hand-list with extra steps.
#   * 3.0.0 is required because it is THE FIRST RELEASE WHOSE DEFAULT BASELINE PINS AN AGENT ELF THIS
#     MACHINE ACTUALLY STAGES — the same class of reason as the 1.20.0 floor, not a fidelity one.
#     2.5.0's newest baseline is `desktop-1.37937.1` (shipped in harness v2.3.0) and it pins agent
#     2.1.246; measured 2026-08-29, that directory is EMPTY here while 2.1.247 carries the ELF. So a
#     record under the 2.5.0 pin resolves no agent and needs `COWORK_HARNESS_ALLOW_AGENT_FALLBACK=1`,
#     which freezes a TOLERATED ELF MISMATCH into a paid cassette — precisely what the 1.20.0 floor was
#     raised to prevent. Under 3.0.0 (baseline `desktop-1.40609.0`, agent 2.1.247) `doctor --tier
#     hostloop` reports `sha256 ✓ vs baseline`. NOTE the scope: this is a property of THIS recording
#     host, not a defect in 2.5.0 — a machine still holding 2.1.246 sees no block.
#     3.0.0 adds NO fidelity debt of its own. Its breaking changes are all `protocol`/L0
#     (`l0_plugin_divergence` -> `l0_host_config_contamination`, L0 finally passing `--plugin-dir`, the
#     new `allow_host_hooks` consent) and we run ZERO protocol scenarios. `CASSETTE_VERSION` stays 12,
#     `MIN_SUPPORTED` stays 9. Four emulation files changed and each was read: `argv.ts` is a pure
#     refactor extracting `pluginDirArgs()` with `baseAgentArgs` behaviour unchanged, `lima.ts` is
#     microvm-only, `protocol.ts` is L0-only, `sync/cowork-sync.ts` is the authoring tool. Baseline
#     delta from what our cassettes actually froze (1.32885.1 / 1.34493.1): the ELF, plus exactly two
#     added `spawn.env` keys (`CLAUDE_CODE_PROMPT_CACHE_TTL`, `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL`);
#     tools, allowedTools, promptTemplate, both sub-agent appends, mountLayout, settings and the
#     allowDomains SET are all identical. Full analysis:
#     docs/internal/2026-08-29-cowork-harness-3.0.0-adoption-plan.md.
#   * 2.5.0 is required for a DIFFERENT REASON FROM EVERY FLOOR BELOW IT, and the difference is the
#     point. Every earlier floor exists because recording bakes the harness version into the artifact.
#     2.5.0 bakes NOTHING: no baseline move, `CASSETTE_VERSION` stays 12, `MIN_SUPPORTED` stays 9, and
#     no emulation directory changed at all (`git diff --name-only v2.4.0..v2.5.0 | grep -E
#     '^src/(runtime|hostloop|staging|agent|egress|sync)/'` is empty). This floor is an AUTHORING GUARD:
#     2.5.0 refuses, at scenario load and pre-spend, a `tool_not_called`/`subagent_tool_absent` naming a
#     tool the tier provably does not serve. All 24 scenarios carrying `subagent_tool_absent: 'Bash'`
#     were vacuous at hostloop, always — the tier aliases the built-in shell to `mcp__workspace__bash`,
#     so the run could never have called `Bash`. Below this floor a re-introduced `'Bash'` records
#     SILENTLY and freezes a vacuous assert into a paid cassette that nothing will ever flag: 2.5.0's
#     new cassette-satisfiability guard covers `tool_not_called` only and explicitly excludes
#     `subagent_tool_absent`, and it lives in upstream's test suite, not in any CLI surface. Neither
#     `lint`, nor the bundled `scenario.py lint`, nor `record --dry-run` catches the class for us — the
#     linters' tier table has no `cowork` row (they are offline and cannot resolve the baseline gate),
#     and the refusal lives in `executeScenario`, which `--dry-run` returns before reaching. This gate
#     is therefore the only thing standing between us and a repeat. Full analysis:
#     docs/internal/2026-08-28-cowork-harness-2.5.0-adoption-plan.md.
#   * 2.4.0 is required because it CHANGES WHAT A HOSTLOOP RECORDING RECORDS. The workspace bash
#     tool's cwd moves from `<session>/mnt/<first-folder-else-outputs>` to the bare session root
#     (`hostLoopCwds`), which upstream measured against desktop-local Cowork on 2026-08-27; the
#     replaced derivation reproduced a prompt claim, not an observed behaviour. Recording below this
#     freezes an emulated cwd production does not use — the emulated-tool-surface trigger in this
#     repo's own re-record rule. Separately, `container` stops offering the built-in `WebFetch`
#     (aliased to `mcp__workspace__web_fetch`), so a sub-2.4.0 recording at that tier freezes a tool
#     inventory production no longer has. The BASELINE did not move (`baselines/` is byte-identical
#     v2.3.0..v2.4.0), so this is an emulation trigger, not a baseline one — the distinction matters
#     because a baseline diff shows nothing. Full analysis:
#     docs/internal/2026-08-27-cowork-harness-2.4.0-adoption-plan.md.
#   * 2.3.0 is required for the RECORDING ITSELF. Its baseline (desktop-1.37937.1, agent ELF 2.1.246)
#     is the first to PIN two spawn-env keys — CLAUDE_CODE_PROMPT_CACHE_TTL=1h and
#     CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL=5m — plus a new opaque env spread site
#     (spawnEnvSpreadCount 31 -> 32). A spawn-env change is a re-record trigger by this repo's own
#     rule. At 2.2.0 `baseline: latest` resolves to desktop-1.34493.1, which carries NEITHER key
#     (verified), so a 2.2.0 recording freezes the pre-pin spawn env. Tool surface and BOTH sub-agent
#     prompt appends are byte-identical across the move — unlike the 1.25.0 trigger, this is not a
#     system-prompt change. Diff the baselines as SETS: `spawnEnvKeys` shows 27 index "changes" that
#     are pure alphabetical shift from inserting two keys. Full analysis:
#     docs/internal/2026-08-26-cowork-harness-2.3.0-adoption-plan.md.
#   NOTE THE HEADER HAS BEEN STALE BEFORE: this line read ">=1.20.0" while the gate below required
#   1.24 — two minors adrift, in the note whose job is to explain the gate. The numeric gate and its
#   FATAL message are ADJACENT LINES (grep -n 'minor.*-ge'); this header is ~110 lines above them.
#   Edit all THREE, then re-read all three.
#   * 1.25.0 is required for the RECORDING ITSELF. Its baseline (desktop-1.32885.1, agent ELF
#     2.1.234) is the first to repoint `spawn.subagentAppendHostLoop` at a re-derived asset: the
#     host-loop SUB-AGENT system-prompt append gained a paragraph telling the model that shell
#     commands start at the VM session root and that anything written outside `<root>/mnt/` — `/tmp`
#     included — never reaches the user and is invisible to its own file tools. That is a SYSTEM
#     PROMPT change at the tier this fleet records at, hence a re-record trigger by this repo's own
#     rule, and it is the split-filesystem fact underneath our whole hand-off design. Baselines
#     resolve by `baseline: latest` = highest-versioned file in the INSTALLED package (not by harness
#     version), and 1.24.0 does not ship desktop-1.32885.1.json — so a 1.24.0 recording is pinned to
#     desktop-1.32352.0 and the previous Desktop family's sub-agent prompt. Exhaustive recursive leaf
#     diff 1.32352.0 -> 1.32885.1: 0 added, 0 removed, 17 changed — 12 provenance/identity, 4
#     `network.allowDomains` ORDER-ONLY (compare as a SET; this trap has fired four times), and the
#     one pointer. spawn.tools / allowedTools / env / promptTemplate / subagentAppend(vm) / hooks /
#     effortDefault / settings / guest / platform / mountLayout are byte-identical.
#   * 1.20.0 is required for the RECORDING ITSELF, unlike the 1.19.0 bump below. Its baseline
#     (desktop-1.26832.0) pins agent ELF 2.1.222 — the only ELF installed on this machine. On a
#     1.19.0 CLI (baseline desktop-1.25927.0, pinned 2.1.221) `doctor --tier hostloop` reports the
#     staged binary as `sha256 ✗ vs baseline` and `parity mount: patch-tolerated (pinned 2.1.221,
#     using 2.1.222)` — it records, but freezes a tolerated ELF mismatch into every cassette. At
#     1.20.0 the same check reads `sha256 ✓`. Nothing else in the 1.19.0 → 1.20.0 move is recording-
#     sensitive: an exhaustive recursive diff of the two baselines leaves spawn.tools /
#     spawn.allowedTools / spawn.env / spawn.promptTemplate / spawn.subagentAppend{,HostLoop} /
#     spawn.hooks byte-identical, and network.allowDomains differs in ORDER ONLY (set-difference is
#     empty both ways — a positional comparison misreads it as a change). See
#     docs/internal/2026-08-07-cowork-harness-1.20.0-adoption-plan.md §2 for the full diff.
#   * 1.19.0 is required NOT for the recording itself (1.19.0 moves no baseline, no spawn env, no
#     prompt — `git diff v1.18.0..v1.19.0 -- baselines/` is empty and `src/` touches only scan /
#     mutate / cassette / chat-result / execute / types, none on a spawn path). It is required for
#     THIS SCRIPT'S OWN privacy step below, which expands `${ALLOW[@]}`. That array no longer carries
#     `--allow-host-inventory`: 1.19.0 exempts a mounted plugin's own agents/skills automatically, so
#     the regex was deleted. On a 1.18.0 CLI the exemption does not exist and the same array reds on
#     240 non-findings (MEASURED via `npx cowork-harness@1.18.0`: exactly 240, exit 1). A stale global
#     CLI therefore clears an older guard and then fails loudly and WRONGLY — which is why the guard
#     moved rather than the allowlist keeping a redundant entry.
#   * 1.18.0 default baseline is desktop-1.25927.0 (agent ELF 2.1.221), and the proactive
#     skill-suggest gate now models ON — a SERVER-SIDE rollout, so it reads ON regardless of Desktop
#     version. `suggest_skills` therefore declares its proactive description plus an optional
#     `trigger` param by default: a TOOL-SURFACE change, which is a re-record trigger by this repo's
#     own rule. A 1.17.0 recording freezes the pre-rollout surface. Field-level diff of
#     desktop-1.24012.9 -> 1.25927.0 (what the committed cassettes recorded against -> the new
#     default), so the debt is sized rather than assumed: the ONLY moving fidelity inputs are the
#     agent ELF and `spawn.env.MCP_TOOL_TIMEOUT` (60000 -> 180000). `spawn.tools`, `allowedTools`,
#     `promptTemplate`, `subagentPrompt`, `options`, `effortDefault`, `settings`, `guest` and
#     `platform` are byte-identical; `network.allowDomains` differs in ORDER only (added [], removed
#     []); the `mountLayout` `projects` row's rw->r correction is documented IN the baseline as
#     "consumed by nothing". Upstream reports its own cassettes replay clean across this move and were
#     re-stamped, not re-recorded.
#     1.18.0 also makes a recording strictly more informative: `record` prints a delta vs the cassette
#     it replaced (`gates 2 -> 0, tool calls 5 -> 4`), and gate option labels are fingerprinted against
#     the skill's own prose — catching a catalog REORDER, which an existence check passes by
#     construction. Neither is available on a 1.17.0 recording; both are exactly the drift this fleet
#     has been bitten by.
# baked into the artifact, so the floor is about RECORDING FIDELITY, not just API stability. Six
# reasons, all permanent-if-missed:
#   * 1.17.0 stops `undelivered_deliverables` firing on EVERY `lane: remote` run. On remote the
#     location arm of the delivery check is correctly off, but the `presentedFiles` arm can never match
#     either — no remote delivery tool is served, so that array is structurally always empty. Every
#     remote run that wrote a file therefore warned "never reached the user", a claim the evidence
#     cannot support. A `deliveryObservable()` predicate now gates it and the new `delivery_unobservable`
#     warn states the gap instead of guessing. Recording `market-sizing-remote-lane` on 1.16.0 freezes a
#     run whose warn set asserts something false about delivery — the signal this fleet's remote lane
#     exists to observe. (This is why the floor moved even though 1.17.0 carries NO re-record debt for
#     the other cassettes: see the fidelity note below.)
#   * 1.16.0 is what STAMPS a `lane: remote` cassette at format v11 — the structural guard that stops an
#     older CLI silently re-scoring it under the wrong delivery contract. Record `market-sizing-remote-lane`
#     on anything older and it is written as v10: readable by every old install, and therefore silently
#     mis-scored by them (an old CLI drops the frozen `lane:` key and can report GREEN on a cassette a
#     current CLI FAILS). `rehash` can re-stamp such a cassette afterwards, but recording on >=1.16.0
#     means never needing that. The stamp is conditional and value-aware — `lane: local`/omitted still
#     writes v10, so the other cassettes are untouched.
#   * 1.14.0 serves `present_files` at the HOSTLOOP tier — the tier this fleet records at. Real Cowork
#     registers that tool unconditionally and alwaysLoad; before 1.14.0 the harness served it only at
#     container, so a hostloop recording froze a toolset one alwaysLoad tool short of production's, and
#     a missing delivery tool can change how a model interprets "deliver this". This is the trigger that
#     makes the next re-record mandatory rather than cadence-driven. (1.14.0 also adds the `lane:`
#     scenario key, which an older LOADER rejects outright — exit 2, not a silent downgrade.)
#   * 1.12.0 fixes a bug that made an UPLOAD-BEARING scenario impossible to record — and spent the paid
#     run finding out. Uploads mount at `uploads/<basename>` and are collected into the cassette's
#     artifacts, but the pre-1.12.0 artifact<->root consistency check measured them against the
#     user-visible roots only, which deliberately exclude uploads; the mismatch threw AFTER the agent
#     run and wrote no cassette. Five of our scenarios are upload-bearing (their `session:` declares
#     `uploads:`): cap-table-antihallucination / -carta / -extract-safe / -lane3-freeform and
#     financial-model-review-smoke. A no-op redaction policy does not save you — the check runs on every
#     record that does not pass `--no-redact`, which this script deliberately does not.
#   * 1.11.0 stamps `environment.harnessVersion` — the recording CLI's own version — into every
#     cassette it writes. It is never backfilled, so a record on an older CLI is provenance-less
#     forever. (Measured 2026-08-06: all 21 committed cassettes DO carry `environment.harnessVersion`
#     — 14 at 1.16.0, 3 at 1.17.0, 3 at 1.19.0, and one at 1.12.0, `market-sizing-smoke`. This line
#     used to claim they carry no `environment` block at all, which was the exact inverse.)
#   * 1.10.0 is the first release whose sandbox declares the skill/plugin discovery SDK-MCP servers
#     (`mcp__skills__list_skills`/`suggest_skills`, `mcp__plugins__list_plugins`/`search_plugins`/
#     `suggest_plugin_install`, all alwaysLoad on container/hostloop/cowork — matching real Cowork). A
#     record on anything older freezes a tool inventory provably missing five tools the product
#     advertises.
# Per-release history: the harness's own CHANGELOG (it stopped duplicating it in its skill at 1.10.0).
# Standing facts this floor does NOT change, all still load-bearing here:
#   * Cassette versions, as of 1.16.0 — the write version is now CONDITIONAL, not a single number:
#     read floor v9; `lane: remote` scenarios write **v11**; everything else still writes **v10**.
#     Of our 21 committed cassettes, 20 are **v10** and one is **v11** — `market-sizing-remote-lane`,
#     under the `lane: remote` rule above; the corpus is no longer lane-free, so the older blanket
#     "all are v10" no longer holds. The hand-authored email canary envelope is v10 too. The v10 rows
#     leave one v-step of headroom above the read floor,
#     not zero. What still holds: a future READ-floor raise refuses every cassette below it at load
#     time, turning a WARN-only staleness advisory into a hard stop across the whole lane, and `rehash`
#     cannot rescue a corpus across such a boundary — only recording can. Bump the canary's
#     cassetteVersion at every future READ-floor raise — see canary/README.md + cowork-replay.yml.
#   * `preRunOrigin` (declared in the v10 schema as of 1.12.0; the recorder was already emitting it) is
#     coupled to `no_unexpected_files`, which ALL our scenarios assert: a cassette recorded from a
#     degraded pre-run walk (`remote-unavailable` / `local-unreadable`) FAILS that assertion as
#     evidence-unavailable rather than passing vacuously. After the next record, diagnose a fresh
#     `no_unexpected_files` failure as a degraded walk first, not as a skill regression.
#   * The `agent_env` session knob (subagent_model / tool_search / disable_experimental_betas) is
#     scrubbed from the operator layer uniformly across tiers — watch for a stray shell export of
#     those three during a record.
# Note on verify-cassettes classes: it has THREE (privacy / staleness / scenario-drift). CI's HARD
# privacy gate in cowork-replay.yml passes `--skip-scenario-drift` because CI cannot re-record; THIS
# script's privacy step deliberately does not (we just recorded, so a fresh cassette must be drift-free).
# NEVER detect staleness by grepping annotation TEXT — annotation text is explicitly not a covered
# surface (harness SPEC §12), and 1.12.0 already moved one class: the non-gating cassette *note* class
# (discovery-surface / prompt-assets / resolved-tier) went `::warning::` -> `::notice::` and a directory
# replay now collapses it to one `N/M cassette(s) - <reason> [kind]` line. The `cassette stale:` lines
# themselves are unchanged and still `::warning::`. Parse the JSON envelope instead.
major="${ver%%.*}"; minor="$(echo "$ver" | cut -d. -f2)"
# `-gt 3` first so a future 4.x passes — a bare minor check would FATAL on 4.0.0.
# The `-ge 0` minor clause is VACUOUS at a .0 floor and is kept DELIBERATELY: the shape
# `[ "$major" -eq N ] && [ "$minor" -ge M ]` is what test_cowork_harness_floors.py's gate regex reads,
# and that test asserts its own pattern matched — so collapsing this to `[ "$major" -ge 3 ]` does not
# simplify the gate, it makes the guard that watches the gate match nothing. It re-earns its keep the
# moment the floor moves off a .0 — as it did at 3.2.0.
{ [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 2 ]; }; } \
  || { echo "FATAL: need >=3.2.0 (have $ver) — see the floor note above"; exit 1; }
if [ -n "${COWORK_AGENT_BINARY:-}" ]; then
  [ -x "$COWORK_AGENT_BINARY" ] || { echo "FATAL: agent binary not executable: $COWORK_AGENT_BINARY"; exit 1; }
fi
docker info >/dev/null 2>&1 || { echo "FATAL: Docker not running (live lane needs it)"; exit 1; }
# Hostloop preflight: validates the native host binary the agent loop spawns AND the staged ELF
# (sha-checked vs baseline) AND the agent/egress images — the tier this fleet records at.
cowork-harness doctor --tier hostloop || { echo "FATAL: doctor --tier hostloop failed — fix the reported prerequisite"; exit 1; }
# Runs root: use the harness default (~/.cowork-harness/runs) so every record appends to the
# cross-run index.jsonl that `cowork-harness stats` reads — a /tmp root would discard that history.
# If overridden, it MUST live outside the mounted plugin tree (recursive-copy + hash pollution).
REPO_ROOT="$(cd .. && pwd)"
case "${COWORK_HARNESS_RUNS_DIR:-}" in
  "$REPO_ROOT/founder-skills"*) echo "FATAL: COWORK_HARNESS_RUNS_DIR must not live under founder-skills/ (it gets mounted + hashed)"; exit 1 ;;
esac
echo "runs root: ${COWORK_HARNESS_RUNS_DIR:-~/.cowork-harness/runs (harness default; feeds the stats index)}"

# --- select scenarios ---
# The bare (no-args) form is a REFRESH of the committed cassettes, so it selects only scenarios that
# already have one. This is a structural guard, not tidiness: scenarios/ can legitimately carry a
# scenario whose cassette is still pending a live record, and the record loop below is `xargs -P`,
# which returns non-zero if ANY child fails — so one never-validated scenario would abort the batch
# and the documented remedy (`git stash push -- cassettes/`) would set aside every good re-record in
# it. Authoring a genuinely NEW cassette is the explicit-name form, after the live-decider flow
# below has settled its gates.
scns=()
if [ "$#" -gt 0 ]; then scns=("$@"); else
  pending=()
  for f in scenarios/*.yaml; do
    n="$(basename "$f" .yaml)"
    if [ -f "cassettes/$n.cassette.json" ]; then scns+=("$n"); else pending+=("$n"); fi
  done
  [ "${#pending[@]}" -eq 0 ] || echo "NOTE: skipping ${#pending[@]} scenario(s) with no committed cassette (record by name once their gates are settled): ${pending[*]}"
fi
for n in "${scns[@]}"; do
  [ -f "scenarios/$n.yaml" ] || { echo "FATAL: scenarios/$n.yaml not found"; exit 1; }
done
echo "re-recording: ${scns[*]}"

# --- cumulative cost pre-flight (harness >=1.15.0) ---
# `record --max-budget-usd` sums each scenario's WORST observed cost from run history and refuses
# BEFORE the first spawn if the batch total exceeds the cap. Two properties that decide how it is used
# here, both measured:
#   * The cumulative pre-flight is CONCURRENCY-INDEPENDENT — identical refusal at --concurrency 1 and 4.
#     Only the running-total MID-BATCH stop requires --concurrency 1, which we do not use.
#   * It must go on a BATCH-form invocation. Threading it into the per-scenario record_one loop below
#     would cap each of ~16 invocations separately and permit ~16x the number typed — a false guarantee
#     the harness's own docs warn about. So this runs once, here, as a gate.
# Deliberately checks the WHOLE scenarios/ dir, which is a SUPERSET of the selected set: conservative in
# the right direction (if the superset fits the cap, any subset does), and it avoids staging a temp dir
# of copies whose relative `session: ../sessions/*.yaml` paths would break.
# WHAT THIS CANNOT DO, stated plainly so the cap is not over-trusted:
#   * It CANNOT catch a runaway. It refuses from HISTORY before spending; a run that goes pathological
#     is not abortable mid-flight (no live cost signal exists), and the mid-batch running-total stop
#     needs --concurrency 1, which we do not use. What it actually catches is COST CREEP — the batch
#     getting historically more expensive (more scenarios, pricier skills) — before you pay for it.
#   * It is BLIND to scenarios with no priced history: they contribute $0, are named in a ::warning::,
#     and make the printed total a LOWER BOUND until each has run once.
# RE-DERIVED 2026-08-27 (cowork-harness 2.4.0, 27 scenarios, ALL PRICED — 131 prior runs on this
# machine, thinnest scenario has 1):
#     estimated batch cost: $118.8390    against the $120 default cap
# ** THAT IS $1.16 OF HEADROOM, AND THE GATE IS SCOPE-BLIND. ** Measured by bisection today:
# --max-budget-usd 120/119 -> rc=0, 118 -> rc=2 ("refused before spending"). The preflight runs over
# the WHOLE scenarios/ dir by design (a deliberate superset), so it compares the all-27 estimate
# REGARDLESS of how many cassettes you are refreshing — "I'm only refreshing 10" does not shrink it.
# One added scenario, or the +/-25% variance noted below, trips it, and the FATAL reads like a broken
# preflight rather than a cap that needs raising. Before any refresh: re-run the one-liner in the
# FATAL message, and raise COWORK_RERECORD_MAX_USD deliberately if the estimate has grown.
# The 2026-08-01 derivation below is KEPT because its METHOD is right (worst-observed per scenario,
# summed, matching the harness's own statistic) — but every NUMBER in it is stale: it was taken at 22
# scenarios / 4 unpriced against a 22-cassette corpus, and the corpus was cut to 10 on 2026-08-24.
#
# SIZING THE DEFAULT — re-derived 2026-08-01 at 22 scenarios / 4 unpriced, from the per-scenario
# worst-observed costs in ~/.cowork-harness/runs/index.jsonl (the same statistic the harness's own
# pre-flight sums).
# ** RE-DERIVE THIS IMMEDIATELY BEFORE SPENDING. Do not inherit the number below. ** It was re-derived
# three times on 2026-08-01 alone and moved every time: ~$55 (19 scenarios) -> ~$72 (21) -> ~$89 (22),
# inside a few hours, while parallel sessions added scenarios and made existing ones costlier. The
# command is one line and it is in the FATAL message below.
#   priced today ...... $57.28 across 18 of 22 scenarios (worst-observed each, summed)
#   + 3 competitive-positioning scenarios, never recorded ......... ~3 x $9.38 = ~$28.15
#     ($9.38 = competitive-positioning-recall-adoption's worst — now the priciest run in the fleet,
#      +32% over competitive-positioning-smoke's $7.12. WORST, not mean, to match the harness's own
#      methodology and because a cap sized off a best case is not a cap. A PROXY — same skill and
#      shape — not a measurement of these three, and the observed cp range is $7.12-$9.38.)
#   + market-sizing-remote-lane, never recorded ................... ~$3.19
#     (= market-sizing-smoke's worst; identical prompt, so the closest proxy there is.)
#   => expected ~$88.6 at 22 scenarios; ~$89.6 once the new container scenario lands (proxy:
#      host-path-canary's $0.94, the only container-tier run with history).
# Default cap $120 leaves ~34% headroom over ~$89.6. Sized against EXPECTED ACTUAL SPEND, not against
# the priced-history sum the gate compares to — those differ by ~$31 today because the gate is blind
# to the 4 unpriced scenarios. Two reasons the margin is not slack:
#   * measured per-scenario variance is ~±25% (cp-smoke alone spans 5.74/5.92/7.12), so a tighter cap
#     refuses a NORMAL batch rather than a runaway — the failure mode that makes a gate get disabled;
#   * after this batch every scenario becomes priced, so the NEXT pre-flight compares ~$89 (not ~$57)
#     against this number.
# ON RAISING IT TWICE IN ONE DAY: a cap that is raised whenever it binds catches nothing, so the raise
# has to be deliberate and reasoned or the gate is theatre. Both raises were — the creep was IDENTIFIED
# and EXPLAINED each time (new scenarios landing; competitive-positioning genuinely getting dearer as
# recall/verification work landed), not waved through. Having to raise it is the gate WORKING: it
# surfaced a ~60% batch-cost increase before anyone paid it. What would be wrong is raising it without
# re-deriving, or sizing it so far ahead of reality that real creep never trips it.
# `--dry-run` cannot be combined with `--rerecord-stale`, which is why this is a separate gate rather
# than a flag on the record itself.
BUDGET="${COWORK_RERECORD_MAX_USD:-120}"
if [ "$BUDGET" != "0" ]; then
  echo "=== cost pre-flight (cap \$$BUDGET; set COWORK_RERECORD_MAX_USD=0 to skip) ==="
  # THE TWO FAILURE EXIT CODES ARE NOT INTERCHANGEABLE. Measured 2026-08-31, identical at 2.5.0,
  # 3.0.0, 3.1.0, and 3.2.0 (the pin as of 2026-09-01):
  #     0 = every scenario loads AND the estimate is under the cap
  #     2 = the BUDGET gate refused (estimate over the cap)
  #     1 = a scenario did not LOAD — `✗ broken: <file>` naming the rejected key
  #   When both apply the answer depends on whether SOME or ALL files are broken — measured, and the
  #   distinction is easy to miss: SOME broken + over cap -> 2 (budget wins); ALL broken + over cap
  #   -> 1 (broken wins). Both land in a sensible branch below, so this is a precision note, not a
  #   hazard. The `✗ broken:` lines go to STDERR, so the `>/dev/null` (stdout only) never hides them.
  #   WHY that split: all-broken means nothing loaded, so there is nothing to spend on and the budget
  #   gate never runs (SPEC.md states this as of 3.2.0). Derivable, not arbitrary.
  #   THE 3.2.0 PIN RAISE (2026-09-01) changed nothing here. The one batch outcome that moves is the REAL arm
  #   (`record <dir/>` with no --dry-run) on an all-broken dir, 2 -> 1; this gate uses the PREVIEW arm,
  #   which already answered 1 at 3.0.0 and 3.1.0. Verified against the full batch matrix, 3.1.0 vs
  #   3.2.0: ten outcomes, exactly one differs.
  #   (The SINGLE-FILE arm also changes at 3.2.0 — policy refusals there go 2 -> 1 — but this gate does
  #   not use that arm. Do not port the boundary across: "above 3.0.1" is wrong, 3.1.0 still exits 2.)
  # This block used to collapse both into "batch cost pre-flight refused", which sent you off to raise
  # COWORK_RERECORD_MAX_USD for a problem that has nothing to do with money: you raise it, re-run, and
  # get the identical message. Keep the branches distinct.
  preflight_rc=0
  cowork-harness record scenarios/ --dry-run --max-budget-usd "$BUDGET" >/dev/null || preflight_rc=$?
  case "$preflight_rc" in
    0) ;;
    2)
      echo "FATAL: batch cost pre-flight refused ON COST — re-run the command below to see the"
      echo "       estimate, then raise COWORK_RERECORD_MAX_USD deliberately or narrow the list."
      echo "       cowork-harness record scenarios/ --dry-run --max-budget-usd $BUDGET"
      exit 1
      ;;
    *)
      echo "FATAL: cost pre-flight exited $preflight_rc — a scenario did not LOAD (above 3.0.1, this"
      echo "       code also covers a policy refusal). THIS IS NOT A COST PROBLEM: raising"
      echo "       COWORK_RERECORD_MAX_USD will not help. The '✗ broken:' line(s) above name the file"
      echo "       and the rejected key. Fix the scenario, then re-run. To see it again:"
      echo "       cowork-harness record scenarios/ --dry-run"
      exit 1
      ;;
  esac
fi

# Authoring a NEW cassette (or one whose gates are hard to pre-script)? Don't iterate THIS batch loop
# on paid records discovering gate phrasing. Use the live-decider flow to answer gates in one pass:
#   cowork-harness record scenarios/<new>.yaml --decider-llm --intent "…"   # a model answers the gates
#   cowork-harness record scenarios/<new>.yaml --decider-dir <fresh-dir>    # YOU answer in-band (gates/answer)
# Then lock the chosen answers into the scenario's `answers:` (cowork-harness verify-run confirms they
# still match the run's gates in ~1s — no paid re-record) and re-record HERE. This batch loop stays
# SCRIPTED-only on purpose: a live decider stamps the cassette `authoring.nonDeterministic`, and
# committed cassettes must be reproducible via this script without a decider.
# Full authoring walkthrough: README.md "Authoring a new scenario".

# --- snapshot the previous cassettes for the normalized-diff review below ---
prev="$(mktemp -d)"
cp cassettes/*.cassette.json "$prev/" 2>/dev/null || true

# --- record (synthetic data only — every scenario subject is fictional Cadence/Acmecorp) ---
# `record` writes EVERY cassette atomically itself — same-directory temp file, then `rename` over the
# target — so a failed, interrupted or OOM-killed run never leaves a partial cassette behind. This loop
# therefore writes `--out` straight to the final path; the temp+mv wrapper it used to carry was
# redundant (documented in the harness's docs/cassette.md: "you do not need to wrap `record` in your own
# temp-file + `mv` dance"). Note what `--out` opts out of, both correct to skip here: the
# refuse-to-overwrite-an-existing-cassette guard (a re-record's entire purpose is to overwrite) and the
# cassettes/-containment check (our paths are literal and script-controlled).
# Bounded parallel pool: runs are fully isolated (per-run dirs, per-container sandboxes); the bound is
# Docker + API pressure, not correctness. Dir-batch mode (`record <dir> --concurrency`) is not used
# because the subset-arg form (rerecord.sh <name>…) composes naturally with this loop.
CONC="${COWORK_RERECORD_CONCURRENCY:-4}"
# NEW-fixture override (harness >=1.18.0). `record` refuses, BEFORE spending, to write a
# host-inheriting recording (protocol/hostloop, or cowork resolving to hostloop — ours) into a
# repo-visible path, because such a recording can freeze the recording machine's own MCP servers /
# account / agents into the cassette. cassettes/ IS committed, so that guard is armed for us and is a
# real safety property for a public repo.
# Re-recording an EXISTING committed fixture in place only WARNS, so the refresh batch needs nothing.
# Authoring a NEW one refuses, and that is the only case this opts out of — per-invocation, so the
# override never becomes reflexive. The `host-inventory` finding class still hard-gates the RESULT via
# verify-cassettes (see privacy-allowlist.sh for why our own plugin's agents are allowed there).
record_one() {
  local n="$1"
  local new_fixture=()
  # NOTE: `--allow-host-inventory-fixture` (here) and `--allow-host-inventory <regex>` (a
  # verify-cassettes finding suppressor) are DIFFERENT flags — see the harness skill's Gotcha 25.
  # This one is record-time consent to write a host-inheriting recording into a repo-visible path.
  # The verify-time one was DELETED from ALLOW at 1.19.0 (see the floor note above); do NOT read that
  # deletion as a reason to drop this. Passing either where the other belongs fails as unknown-flag.
  [ -f "cassettes/$n.cassette.json" ] || new_fixture=(--allow-host-inventory-fixture)
  cowork-harness record "scenarios/$n.yaml" --out "cassettes/$n.cassette.json" "${new_fixture[@]}" \
    || { echo "RECORD FAILED: $n"; return 1; }
}
export -f record_one
printf '%s\n' "${scns[@]}" | xargs -P "$CONC" -I{} bash -c 'record_one "$@"' _ {} \
  || { echo "FATAL: at least one record failed — set aside partials with 'git stash push -- cowork-tests/cassettes/' (NOT 'git checkout --': this tree is permanently dirty by design and checkout has destroyed uncommitted work here) and re-run"; exit 1; }
recorded=()
for n in "${scns[@]}"; do recorded+=("cassettes/$n.cassette.json"); done

# --- post-run checkers (informational — not a second pass/fail gate) ---
# delivery_check.py / gate_prefix_check.py are implemented + unit-tested but were invoked
# nowhere until now. Point them at the REAL kept run dir this record left under the runs
# root (harness default ~/.cowork-harness/runs, or $COWORK_HARNESS_RUNS_DIR): `status
# --latest-for` resolves it by actual run time, not directory mtime, so a concurrent batch
# (this loop runs at --concurrency "$CONC") can't hand back a sibling scenario's dir.
# Non-fatal by design: read the printed findings before committing, same as the normalized
# diff below — these are reviewer signal, not a gate that blocks the batch. (CI wires the
# same two checkers as a HARD/WARN pair respectively against the committed cassettes
# directly, since CI never produces a run dir at all — see cowork-replay.yml.)
echo "=== post-run checkers: delivery completeness + gate no-change-prefix (informational) ==="
for n in "${scns[@]}"; do
  run_dir="$(cowork-harness status --latest-for "$n" --output-format json 2>/dev/null | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin)["outDir"])
except Exception:
    pass
' 2>/dev/null || true)"
  if [ -z "$run_dir" ] || [ ! -d "$run_dir" ]; then
    echo "  $n: could not resolve a kept run dir via 'status --latest-for' — skipping"
    continue
  fi
  echo "  --- $n ($run_dir) ---"
  python3 delivery_check.py "$run_dir" --pretty || true
  python3 gate_prefix_check.py "$run_dir" --at-most-one --pretty || true
done

# --- verify with the SAME gates as CI, SCOPED to what we just recorded ---
# A subset run must NOT verify the whole dir: the un-refreshed cassettes are legitimately still stale
# and would staleness-fail the batch. Full run (no args) -> the dir; subset -> only the refreshed files.
source ./privacy-allowlist.sh
echo "=== lint ==="; cowork-harness lint scenarios/
if [ "$#" -gt 0 ]; then targets=("${recorded[@]}"); else targets=("cassettes/"); fi
for t in "${targets[@]}"; do
  echo "=== privacy: $t ===";   cowork-harness verify-cassettes "$t" --skip-staleness "${ALLOW[@]}"
  # Staleness is a HARD gate here: a just-recorded cassette passes its own staleness check, so a
  # [stale] here means real drift (fileSigs names the file); fail loud. (CI keeps staleness WARN
  # because CI can't re-record; here we just did, so green is the correct expectation.)
  echo "=== staleness: $t ==="; cowork-harness verify-cassettes "$t" --skip-privacy
  # Write replay JSON to a temp file, THEN parse. 0.28.0 FIXED the underlying bug (`replay
  # --output-format json` used to truncate its stdout at the 64KB pipe buffer via async process.stdout +
  # exit; now sync writeSync), so a direct pipe is safe on >=0.28.0 — but the file redirect is kept as
  # cheap defensive insurance against any future async-stdout regression, and costs nothing.
  echo "=== replay: $t ===";    rep_tmp="$(mktemp)"; cowork-harness replay "$t" --output-format json > "$rep_tmp"
  python3 -c 'import sys,json;d=json.load(open(sys.argv[1]));ok=d["ok"] and all(r["result"]=="success" for r in d["results"]);print("replay ok=",ok);sys.exit(0 if ok else 1)' "$rep_tmp"
  rm -f "$rep_tmp"
done

# --- normalized drift review (primary): per-run noise masked, what remains is real drift ---
# `diff` exits 1 on differences by design — informational here, hence `|| true`.
for f in "${recorded[@]}"; do
  b="$(basename "$f")"
  [ -f "$prev/$b" ] && { echo "=== diff (normalized): $b ==="; cowork-harness diff "$prev/$b" "$f" --view all || true; }
done
rm -rf "$prev"

echo "DONE. Review the normalized diffs above (primary) + 'git diff -- cowork-tests/cassettes/' (synthetic only), then commit by name."

# --- cross-run health + disk hygiene (informational tail; never fails a successful record) ---
echo "=== stats (last 20 runs/scenario) ==="; cowork-harness stats --last 20 || true
echo "=== prune kept runs (keep last 5) ===";  cowork-harness prune --keep-last 5 || true
# Corpus inventory LAST, because a re-record is exactly when the cassette counts and version
# spread change — and those are the facts that have repeatedly gone stale in prose. Print them
# here so the person who just changed them sees the new truth, rather than trusting a number
# written into a README months ago.
echo "=== cassette inventory (post-record truth; update any prose you copy it into) ==="
python3 "$(dirname "$0")/cassette_inventory.py" || true
