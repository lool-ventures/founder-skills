---
paths:
  - "CHANGELOG.md"
  - "VERSIONING.md"
  - "pyproject.toml"
  - "founder-skills/.claude-plugin/plugin.json"
  - ".github/**"
  - "scripts/pre-tag.sh"
  - "cowork-tests/rerecord.sh"
  - "cowork-tests/scenarios/**"
  - "founder-skills/tests/test_cowork_harness_floors.py"
  - "founder-skills/tests/test_release_gating.py"
  - "founder-skills/tests/test_branch_gate_check.py"
  - "CONTRIBUTING.md"
  - "founder-skills/tests/test_release_notes.py"
  - "founder-skills/tests/test_scoring_changes_check.py"
  - "founder-skills/tests/test_actions_allowlist.py"
  - "founder-skills/tests/test_pre_tag_covers_ci.py"
---
# Release Process

**Pushing `main` ships.** Users install from the marketplace clone that tracks `main`, so the paid gate (`deck-review-e2e-smoke` and `mutation-corpus` in `.github/workflows/skill-quality.yml`) runs ONCE per release, on a `release/vX.Y.Z` branch BEFORE `main` moves, dispatched by hand. The tag push does not run it again: `verify-branch-gate` checks the tag against both `pyproject.toml` and `founder-skills/.claude-plugin/plugin.json` versions, checks the CHANGELOG's Scoring changes section, and finds the green dispatched run at the tagged commit (`.github/scripts/branch_gate_check.py`); then `publish-release` creates the GitHub Release. `scripts/pre-tag.sh vX.Y.Z` runs the version and Scoring checks locally first. Per-PR e2e is off by default; opt in via manual dispatch for architectural-surface PRs (list in `.claude/rules/e2e-dispatch.md`).

## Release ordering

0. **Refresh cowork cassettes** (release cadence, paid, local): `cowork-tests/rerecord.sh`. It preflights `cowork-harness doctor --tier hostloop` (needs Docker, the `:2` agent image, and BOTH staged agent binaries — the Linux/arm64 ELF and the native Desktop host binary the hostloop agent loop spawns), records in a bounded parallel pool, prints a normalized `cowork-harness diff` per refreshed cassette (the primary drift review), and tails `stats` + `prune` (runs land in `~/.cowork-harness/runs`, so `stats` can trend reliability across re-records). `fidelity: cowork` records at native hostloop; host paths are stripped by `cowork-tests/.cowork-redact.json`, and `record` refuses a cassette whose asserts or `computer://` links redaction broke. The cowork-replay staleness gate is WARN-only, so cassettes drift between releases. Skip only if nothing under `skills/`, `scripts/`, `references/`, `agents/` or `plugin.json` changed since the last refresh — see "Cassettes and the assert block" below. Every tier records a local session. New Pro and Max Cowork tasks run only in a cloud session (observed 2026-10-07, Desktop 2.26454.0; their scheduled tasks keep a "Require this computer" switch, off by default), so for those founders a green refresh is evidence about behaviour, not about the lane they get — see standing risk (5). Team org tasks run in a cloud session too (observed 2026-10-25: a new Team task reported `CLAUDE_CODE_ENTRYPOINT=remote_cowork`), so a green refresh is not evidence about Team founders' lane either.

**cowork-harness version posture.** Three postures, per site — never collapse them into one number:

* **CI selectors are PINNED EXACTLY at `5.0.0`** — the four workflow `version:` inputs, the `skill-static-analysis` `npm i -g`, and the install lines in `CONTRIBUTING.md`, CLAUDE.md and `pyproject.toml`. Never a caret: a range auto-adopts upstream releases into CI with nobody choosing it, and CI steps have gone red on rules the harness added. Raise the pin in a deliberate adoption pass (write the adoption plan first, under the internal docs dir), never to chase a red.
* **RECORDING floor `>=5.0.0`** — `cowork-tests/rerecord.sh`, four sites; find the gate with `grep -n 'minor.*-ge'`, never by line number. The gate keeps the shape `-eq <major> && -ge <minor>` because the floors test's regex READS that shape — "simplifying" it blinds the guard, not the gate. The floor moves for four distinct kinds of reason (plus a fifth, 4.2.0's, below), and only the first is a re-record trigger. 5.0.0 holds it now (2026-11-14), as a major and for reason (1): its `latest` (desktop-4.23118.0) pins agent 2.1.317, and the hostloop agent no longer inherits the operator shell (only PATH, HOME, LOGNAME, SHELL, USER, TERM, CLAUDE_CODE_TMPDIR and `agent_env.passthrough`); our hooks read only `CLAUDE_PLUGIN_ROOT` and `CLAUDE_ENV_FILE`, which the agent sets. Desktop stages 2.1.321, newer than any published harness pins, so `doctor` passes as patch-tolerated with a sha256 mismatch; the owner chose to record under it (2026-11-14), and every recording made under 5.0.0 here carries an `agent-version` note until a harness pins the staged agent. 4.11.0 held it before, for reason (3) plus a moved `latest`, and it IS a re-record trigger: its `latest` (desktop-3.1623.4) pins the staged agent 2.1.308 (sha256 match; under 4.10.0 `doctor` reports its pinned 2.1.299 pruned and falls back with a mismatch), and its spawn env adds `CLAUDE_CODE_ENTRYPOINT_ON_REQUESTS=""`, reason (1), though no script of ours reads it; the system prompt and allowlist are unchanged. No re-stamp: the agent moved and no committed cassette ran 2.1.308. 4.10.0 held it before, for reason (3) plus a moved `latest`, and it is NOT a re-record trigger: 4.6.0 pinned agent 2.1.293, which Desktop 2.42304.0 has pruned (4.6.0's `doctor` falls back to 2.1.299 with a sha256 mismatch), while 4.10.0's `latest` (2.42304.0) pins the staged 2.1.299 (sha256 match); spawn, mount layout, network and the system prompt are unchanged at every `latest` hop from 2.26454.2, and no cassette was re-stamped, because the agent moved and no committed cassette ran 2.1.299. 4.6.0 held it before, for the same reason: 4.5.0 pinned agent 2.1.289, which Desktop no longer staged, while 4.6.0's `latest` (2.26454.2) pinned the staged 2.1.293; 2.26454.2 differs from 2.26454.0 only in the agent, so `deck-review-smoke`, recorded under 4.5.0 on 2.1.293, was re-stamped. 4.5.0 held it before that, for reason (1) on all three inputs: the agent moved 2.1.284 -> 2.1.289 (`latest` = 2.26454.0), the spawn env turned auto-memory OFF at every tier, and the hostloop bash tool runs `bash -c` and rewrites a plugin's host path to its VM mount; the cassettes recorded before it stay `[stale] baseline moved` (WARN in CI) until the release re-records them. The reasons: (1) a release changes a fidelity input (emulated tool surface, spawn env, system prompt); (2) a release adds a record-time field that cannot be backfilled (`environment.harnessVersion` 1.11.0, `environment.model` + session fingerprint 3.1.0 — `rehash` migrates hash FORMATS, never fingerprint shape, and cannot cross a cassette-version boundary) or refuses pre-spend — in `executeScenario`, past the loader — a scenario older versions accepted (2.5.0; `--dry-run` reports that class, in `refusals[]` since 5.0.0 and in `inputErrors[]` 4.1.0-4.x); (3) the pinned agent ELF no longer matches what Desktop stages — `doctor --tier hostloop` then reports a tolerated mismatch that a paid cassette would freeze, and recording needs `COWORK_HARNESS_ALLOW_AGENT_FALLBACK=1`; (4) a scenario asserts a key newer than the CLI — the loader HARD-REJECTS with `Unrecognized key`, `lint` on the same file exits 0, and `cassetteVersion` does not bump, so nothing warns (1.24.0, `file_absent` / `question_options`). 4.2.0 held this slot for a FIFTH kind of reason, NOT a re-record trigger: its `latest` baseline moved to 2.16120.0, so a cassette recorded under an older CLI is stale against the CI pin the day it is recorded. Its one fidelity-input change (spawn env: `PYTHONDONTWRITEBYTECODE=1`) was assessed and the committed cassettes were RE-STAMPED (`fingerprint.baseline`, one line each), not re-recorded: at hostloop the variable reaches only the host-side hooks, never the shell the skill scripts run in, and bytecode changes nothing a cassette records. (4.0.0 held this slot before, for reason (3) and the major-version trigger: its pinned agent ELF matches the one Desktop stages (2.1.284; `doctor` reports a sha256 match), where 3.10.0's did not.) (3.10.0 held this slot before, for reason (1): the host-loop spawn moved -- the agent process runs at `/var/empty` (or a per-run `host-cwd`), with `--settings`, deny rules on `--disallowedTools` and the path gate's re-anchoring (`src/runtime/hostloop.ts`, `src/runtime/argv.ts`), plus one system-prompt line (`hostloop-prompt.ts`). Under it a relative file-tool path is refused as production refuses it; a cassette recorded below it freezes a world where one passes.) (3.8.0 held this slot before, for reason (1) on all three inputs at once: `runtime/argv.ts` passes `--include-hook-events`, `hostloop/{skills,workspace}-handler.ts` move the emulated tool surface, and `prompt.ts` / `prompt/subagent-manifest.ts` move the system prompt. It is also the first release under which a hook is assertable at all.) (3.6.0 held this slot for reasons (1) and (3): the `CLAUDE_CODE_DESKTOP_APP_VERSION` injection and the ELF Desktop 2.2553.1 stages.)
* **Replay skip-guard `>=3.8.0`** (no upper bound: the check is `version < (3, 8, 0)`) — `test_cowork_cassette_replay.py::_MIN_HARNESS`, the only replay-floor site. It decides whether the local replay test runs at all, not which CLI CI installs; raising it turns a below-floor developer's red into a silent skip. It moved off `^2.1.0` on 2026-09-24 because `market-sizing-remote-lane` froze `hook_event_fired: Stop`, which an older CLI cannot grade — a scenario needed it, which is the only reason it ever moves.

`test_cowork_harness_floors.py` pins every site, CLAUDE.md and the `.claude/rules/` files that carry a pinned sentence included, and `uses:` (action) vs `version:` (CLI) major agreement — the two move independently. Read values from it; a version number in prose here has been stale on four separate occasions.

**Adopting a new harness release** — the checklist that has been wrong most often:
- Diff `src/` and `schema/` WHOLE between tags. A prefix list (`baselines/`, `src/runtime/…`) is a hand-list with extra steps; it missed a moved session fingerprint (3.2.0).
- Diff the baseline JSON leaf-by-leaf; compare `network.allowDomains` as a SET (order-only churn has read as a change three times); name what moved rather than listing what you checked (a hand-list once "verified" three keys that do not exist, and classifying the whole `provenance.*` prefix as noise missed a flipped gate — 3.0.0's `subagentPromptServerOverride` ON means no cassette can prove what sub-agent prompt text production sent). `baselines/` byte-identity is NOT "no fidelity debt" — 2.4.0 moved emulation code (`hostLoopCwds`, `container` `WebFetch` aliasing) with an identical baseline, and spawn-env changes in `src/runtime/argv.ts` (`NO_PROXY`, `CLAUDE_CODE_DESKTOP_APP_VERSION`) are invisible to any baseline diff.
- Our baseline is whatever `latest` resolves to (nothing declares `baseline:`): each cassette's `fingerprint.baseline` is what it recorded against, `latest` is the numerically highest file in the harness's `baselines/` dir. Re-derive after any `sync` or Desktop bump.
- Run every token-free surface before and after — `replay` over all cassettes, `verify-cassettes` with the expanded allowlist, `lint --strict --min-severity WARN`, `record --dry-run` (both arms), `analyze-skill --strict` (exits 0 on advisory findings; only `error` gates), `lint-skill --json` through `cowork-tests/lint_skill_gate.py` — and diff the outputs. Settle an exit code by measuring, never by inheriting upstream prose.
- Standing risks with no cassette tripwire: (1) the elicitation-conflict gap — every SKILL.md's `AskUserQuestion` "(NOT plain chat)" directive can be silently overridden by the host's injected form guidance, unobservable by any harness run; cap-table's Step 0 hand-off gate is the one site without the fallback sentence (its fallback is scoped to a different gate). (2) The `Artifact` tool has been seen in a real local session (2026-10-03); the harness still serves it at no tier (4.9.1's `sync` records its conditions in the baseline, nothing more). (3) Real Cowork re-syncs plugins into a live session — a quick pass about every 20 minutes, a full pass at app start and hourly; the harness stages once and never re-stages — a limit on what a green cassette proves. (4) `COWORK_EGRESS_PROXY` / `COWORK_DOCKER_NETWORK` never worked and were removed in 1.20.0 — do not add them from an old README (`COWORK_PROXY_IMAGE` is live). (5) No tier models a cloud session, the lane new Pro, Max and Team Cowork tasks run in (Pro and Max observed 2026-10-07; Team 2026-10-25, a new task in the Team org reporting `remote_cowork`). An "Only on this computer" switch does not show the lane: Team tasks have been seen going to the cloud with it ON, so check `CLAUDE_CODE_ENTRYPOINT` in the task's own shell. Observed there on 0.26.0 (2026-10-25): the session runs the account's synced copy of the plugin (one folder per org and account, under the container's synced-plugins dir), not the marketplace clone; the main thread has a page-fetch tool and, in a session in auto mode, opening a page asks no approval (whether it asks outside auto mode is not measured; its result is a summary, so a recorded passage can be a paraphrase); tesseract and pdftoppm are present, and Step 3.95 read the image deck; an attachment lands in `/mnt/user-data/attachments/<conversation-id>/` with an `<8-hex>-` name prefix (that run's `--uploads` exited 3, since `uploads/` was empty; it now answers the single attachments folder holding a file, after the two uploads folders, and exits 3 naming the ambiguity when several do). Placement varies: on 0.27.3 (2026-11-04, n=1) the same attachment landed both there, prefixed, and in `/mnt/user-data/uploads/` under its plain name, read-only, so `--uploads` answered `uploads/` and a skill read the plain name; the attachments-only branch has not yet run in a real session. There a skill typed as a conversation's first message is expanded outside Claude Code: tokens and `$ARGUMENTS` arrive as written and the base directory does not exist. Hooks and sub-agents still work on that path. No recording can reproduce it; only a probe in a real cloud session can. 4.8.0's `device_bridge` (`lane: remote` + `fidelity: container`) narrows this: it serves `device_bash` / `get_device_info` against copies of the connected folders. It does not model the first-message facts above, and it never serves `device_commit_files`.
- The upstream hook-detection fix (manifest-declared hooks) is gated to `protocol` only; our `SessionStart` hook disclosure cannot fire at hostloop. Not a bug for us; recorded so nobody expects it.

**Cassettes and the assert block** — rules, not history (the history is archived locally with the per-release adoption plans):
- Staleness is skill-scoped (each scenario's `skills:` key) but the mount is whole-plugin — narrowing the mount is what reintroduces a false-green. "Shared root" = everything NOT under `skills/<x>/`, so `plugin.json` and the plugin-root `scripts/`, `agents/` and `references/` stale the fleet too (`skills/feedback/` is skill-scoped now, no longer shared root). In practice every cassette is already fleet-stale on baseline drift, so "just re-record that skill's lanes" leaves the rest red. Derive corpus facts with `python cowork-tests/cassette_inventory.py` and `cowork-harness verify-cassettes cowork-tests/cassettes --skip-scenario-drift`; never from prose. Bare `rerecord.sh` refreshes only scenarios with a committed cassette (it prints what it skipped); author a new one by name. After a refresh: confirm green, commit `cassettes/` by name, then grep the new cassettes for improvised shell (`curl|wget|pip install|uv run|npx|apt-get|git clone`) — egress from bash has been live since 1.20.0 and no SKILL.md sanctions it.
- Plain `replay` evaluates the assert block FROZEN in the cassette, never the on-disk YAML. An assert added after recording is invisible to CI; one deleted after recording still runs. After any `assert:` edit, diff `json.load(cassette)["scenario"]["assert"]` against `yaml.safe_load(scenario)["assert"]` key sets.
- `replay <cassette> --assert-from <yaml> --write` persists the on-disk block for free — but `--allow-failing` disables its only drift gate, so a block written that way passes against pre-drift events, which is worse than silence (silence prompts a re-record; green does not). Do not cite those greens as evidence about current gate handling — `deck-review-gate-stop` (recorded fresh) is the evidence. Sequence a write-back with the fix, never before it. A refusal (`answers drifted`, `prompt drifted`) means a real re-record; re-derive which lanes refuse with a loop of `replay <cassette> --reassert` checking rc=2.
- `deck-review-numeric-chain` is in `_NO_CASSETTE_ALLOWLIST` and must never be recorded: a frozen recording would preserve the defects it exists to surface.
- Re-record trigger: every harness major, and any release whose changelog touches one of the three fidelity inputs. Nothing automatic flags it — the changelog is the authority. The one sanctioned exception is upstream's re-stamp (`docs/cassette.md`, "Clearing a drifted baseline"): when a baseline moves and the change reaches neither the process running the skill's scripts nor anything a cassette records, set `fingerprint.baseline` by hand and record the argument in the adoption plan (4.2.0 is the precedent; its plan states why). 4.5.0 is NOT one: upstream forbids re-stamping across 4.3.0's auto-memory change, and its agent moved. 4.6.0 IS one, for a cassette recorded on agent 2.1.293 only (`deck-review-smoke`): its baseline moved only in the agent the recording already ran; the 4.5.0 ban still covers every cassette recorded before 4.5.0. 5.0.0 is NOT one (a major, the agent moved 2.1.308 -> 2.1.317 and the spawn env changed). 4.11.0 is NOT one either: the agent moved 2.1.299 -> 2.1.308 and the spawn env changed. 4.10.0 is NOT one: the agent moved 2.1.293 -> 2.1.299 and no committed cassette ran 2.1.299. A re-stamp is an assertion the tool cannot check. `rerecord.sh` enforces a **harness floor of `>=5.0.0`**.

0.5. **Run the gates `pytest` does not.** A green `uv run pytest` is NOT a green CI. Two separate
   gates have to pass before you tag, and neither is reachable from the test suite:
   - **mypy over all EIGHT directories** — the six `skills/*/scripts/` dirs, **`founder-skills/tests/`
     and `founder-skills/scripts/`** (`ci.yml:35-42`; it is easy to miss by reading only the first few
     `- run:` lines). **The steps run under `-e`, so the first failure MASKS every later one**:
     clearing one error does not turn the job green, it advances it to the next failing step. v0.7.0
     burned two tags on exactly this — a `verify_positioning.py` shadowed-variable error hid 8 errors
     in `tests/`.
   - **`uv run ruff format --check .` and `uv run ruff check .`**.
   Run all of them (`scripts/pre-tag.sh` runs them all), then bump. Each failure the
   branch run finds costs another paid run. The tag run checks only the version, the Scoring
   changes section and the branch run's evidence, which pre-tag and step 6 check first.
1. Bump versions in `pyproject.toml` and `founder-skills/.claude-plugin/plugin.json` (must match)
2. Update `CHANGELOG.md` — and **read the diffs, not the commit messages**. The v0.7.0 pass found a
   duplicated entry, four script filenames in user-facing text (0.6.0 names zero `.py` to users), and
   three internal war stories. Match the format the previous release established (titled release +
   `### Highlights`, then Added / Changed / Fixed) rather than dumping bullets under `Fixed`.
   Every release section has `### Scoring changes` ("None." when nothing changed): it is a downstream
   contract, checked at tag time against the scoring-file registry in `.github/scripts/scoring_changes_check.py`.
3. `git commit -s -m "release: vX.Y.Z"`, then `scripts/pre-tag.sh vX.Y.Z`, which also checks the
   tag against both manifests and the Scoring changes section (a dispatched gate run skips both).
   Before anything leaves the machine: `main` must fast-forward from `origin/main`
   (`git fetch origin main && git merge-base --is-ancestor origin/main HEAD`; never `--force` to
   `main`), `python3 scripts/privacy_guard.py --tree --no-names` and `--range origin/main..HEAD` must
   be clean, and `git diff --stat origin/main..HEAD` must name nothing under `docs/internal/`,
   `docs/plans/` or `evals-local/`.
4. **Open the release PR from a branch; `main` does not move yet.** Write the notes to a file first,
   so a failure of `changelog-notes.py` stops here rather than opening a PR with an empty body:

   ```bash
   git push origin HEAD:refs/heads/release/vX.Y.Z
   python3 .github/scripts/changelog-notes.py vX.Y.Z > /tmp/notes.md
   gh pr create --base main --head release/vX.Y.Z --title "release: vX.Y.Z" --body-file /tmp/notes.md
   ```

   The PR is the review page and the record. It runs `ci.yml` (lint, typecheck, tests, the
   name-free privacy guard, manifest validation), `version-check.yml`, skill-quality's free contract
   tests and its self-test of the tag-time check (`branch-gate-selftest`), `cowork-replay.yml` when its paths changed, and DCO. It holds only the release range, so
   every commit in it must carry a sign-off.
5. **Run the paid gate on the branch:** `gh workflow run skill-quality.yml --ref release/vX.Y.Z`.
   A dispatch runs `deck-review-e2e-smoke` (the three e2e lanes) and `mutation-corpus`, never
   `publish-release`. Wait for both green.
   - A red lane: read the failing assertion before anything else. A re-run is PAID (the three lanes
     again), so re-run once only when the assertion reads as LLM variance; never re-run blind.
   - A real failure: the version has not shipped, so it needs no new bump. Put the fix below the
     release commit, so `release: vX.Y.Z` stays last (amend it in with `git commit --amend -s`, or
     commit it and rebase it under the release commit), add it to that version's CHANGELOG section,
     re-run `scripts/pre-tag.sh vX.Y.Z`, then
     `git push --force-with-lease origin HEAD:refs/heads/release/vX.Y.Z` and dispatch again. A lease
     refused with `(stale info)` means the local view of the branch is old: `git fetch origin
     release/vX.Y.Z` and push again. The bump-again rule in VERSIONING.md applies only once `main`
     carries the version.
   - **The three opt-in deck-review lanes** (contradiction, numeric operators, image deck) run only on request:
     `gh workflow run skill-quality.yml --ref release/vX.Y.Z -f extra_deck_lanes=true`, a SEPARATE
     dispatch from the gate's (about $10-30 more). That run repeats the gate's lanes as well, and a red
     extra lane reds its job; `branch_gate_check.py` accepts any green dispatched run at the commit, so
     a red extra run does not block the tag once the plain gate run is green. Run them when the numeric
     chain or its proposer prompt changed. That dispatch also installs `tesseract-ocr` and `poppler-utils` for
     the image-deck lane (`RUN_PAID_E2E_OCR`), the only paid run that reaches Step 3.95; on it the market-sizing
     lane's scanned upload meets a real tesseract too, which is expected. Locally (billed, the tools on PATH):
     `RUN_PAID_E2E=1 RUN_PAID_E2E_OCR=1 uv run pytest founder-skills/tests/test_e2e_deck_review.py -k image_deck -v -m e2e --tb=short -s --basetemp /tmp/fs-e2e`.
   - **The opt-in financial-model-review unclassified-revenue-model lane** runs only on request:
     `gh workflow run skill-quality.yml --ref release/vX.Y.Z -f extra_lanes=true` (about $5-15), a
     separate dispatch from the gate's, with the same posture as the deck lanes above (the env
     `RUN_PAID_E2E_FMR_UNCLASSIFIED` is set from the input, never an `if:`; the lane is named in
     `ALLOWED_SKIPS`). It is a measurement: a red on its first assertion reports what the run wrote for
     `company.revenue_model_type` / `unclassified_reason`, not a regression. Locally (billed):
     `RUN_PAID_E2E=1 RUN_PAID_E2E_FMR_UNCLASSIFIED=1 uv run pytest founder-skills/tests/test_e2e_financial_model_review.py -k unclassified -v -m e2e --tb=short -s --basetemp /tmp/fs-e2e` (`--basetemp` OUTSIDE `~/.claude`).
   - **The market-sizing compaction lane** (`test_market_sizing_compaction_lane`) is local only:
     `RUN_PAID_E2E_MS_COMPACTION` is never set by the workflow, and the lane is in `ALLOWED_SKIPS`. It sets
     `CLAUDE_CODE_AUTO_COMPACT_WINDOW` to the floor so the run compacts mid-way, writes
     `compaction_report.json` (C, R, F, as `_e2e_harness.compaction_report` defines them; written on a
     budget stop too), and asserts only that the run completed. It refuses to start without
     `RUN_PAID_E2E_MODEL` (a pinned model id) and caps each run with the SDK's `max_budget_usd`
     (`RUN_PAID_E2E_MAX_BUDGET_USD`, default 25). C is the main thread's own `compact_boundary`; a run
     without one placed in the stream fails as VOID, and is not a result.
6. **Green: fast-forward `main`, then tag.** Green means the paid gate AND every PR check
   (`gh pr checks release/vX.Y.Z`): the push to `main` goes around branch protection
   (`enforce_admins` is false), so nothing else enforces lint, typecheck, tests, DCO or the review.
   Then confirm a green run tested `git rev-parse HEAD`, with the check the tag will run (free):
   `GH_REPO=lool-ventures/founder-skills python3 .github/scripts/branch_gate_check.py --sha "$(git rev-parse HEAD)" --tag vX.Y.Z`.

   ```bash
   git push origin HEAD:main
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```

   The push to `main` is what ships. Per GitHub's behaviour, the PR is marked merged when its head
   lands on `main`; never use its merge, squash or rebase buttons — a merge commit lands unsigned
   and a rebase rewrites the SHAs the gate tested. The tag push does NOT run the paid gate again:
   it runs `contract-tests` and `verify-branch-gate` (version, Scoring changes, and the green
   dispatched run at this commit), and `publish-release` waits on both. The tag run costs nothing.
   - A red `verify-branch-gate` because the branch run was still in progress, or a transient API
     error: `gh run rerun <tag-push run id> --failed` (free). Re-running the failed jobs re-fires
     `publish-release` too.
   - No green branch run at this commit (a hotfix, or the run was at another commit): the override.
     `gh workflow run skill-quality.yml --ref vX.Y.Z` runs the paid jobs at the tag's commit (a
     dispatch never publishes); once green, `gh run rerun <tag-push run id> --failed`. Two limits:
     a run can be re-run only within **30 days** of its first attempt, and a re-run executes the
     workflow file **at that run's own commit** (so a tag whose commit predates the
     `verify-branch-gate` job re-runs the old paid tag job instead). Past either, publish by hand
     (step 8's command).
   - A real failure (a wrong version or Scoring section): `main` already shipped this version. KEEP
     the tag — it marks what shipped — and let it stand with no Release; then release the next patch
     through these same steps. Deleting it breaks the next release: `scoring_changes_check.py` diffs
     from the tag of the previous CHANGELOG section and fails when that tag is missing. Never re-tag
     a version `main` has carried.
7. **Delete the release branch if it still exists.** This repository is set to delete a merged PR's head branch (`delete_branch_on_merge`), and the PR is marked merged when its head reaches `main`, so it is usually gone already: `git ls-remote --exit-code origin refs/heads/release/vX.Y.Z && git push origin :release/vX.Y.Z`.
8. **The GitHub Release is now created FOR you — do not run `gh release create` by hand.**
   `publish-release` in `skill-quality.yml` fires on a tag PUSH (and only a push — a
   `workflow_dispatch` on a tag ref is excluded, or dispatching the rehearsal would publish), after
   `verify-branch-gate` finds the green branch run. It builds the notes and the title from `CHANGELOG.md` via
   `.github/scripts/changelog-notes.py`, which emits exactly `vX.Y.Z — <title>` to match the
   releases published by hand before it existed.

   **Running it manually now races the workflow**; whichever loses reds on "release already exists"
   (there is no `--clobber` and no existence check). If you need to publish by hand — the automation
   failed, or you are backfilling an old tag — this is the command it replaces:

   ```bash
   # notes = that version's CHANGELOG section; title = the section's own "— <title>" text
   gh release create vX.Y.Z --verify-tag --latest \
     --title "vX.Y.Z — <changelog title>" -F <(python3 .github/scripts/changelog-notes.py vX.Y.Z)
   ```

   **Rehearse the notes without tagging** (free, publishes nothing):
   `gh workflow run skill-quality.yml -f verify_release_notes_for=vX.Y.Z`.

   A **tag** and a **Release** are different objects: a Release is created only by `gh release create`
   or the web UI. Because this step was never written down, **four tags shipped with no Release**
   (v0.3.1, v0.6.0, v0.7.0, v0.7.1) and the repo's "Latest" badge sat on **v0.4.7 for two months** while
   the project kept shipping — a public repo advertising itself as stale on the day it released.
   Backfilled 2026-08-07; v0.3.1 deliberately left alone. Nothing was broken by the omission (users
   install from the marketplace clone tracking `main`, so `plugin.json#version` there is what they get)
   — the cost is entirely perception, which is why nothing failed and it drifted for four releases.

   **The release ENDS here.** `sync-test-repo.sh` is deliberately NOT a release step — see below.

   Two mechanics worth knowing: `--verify-tag` aborts if the tag isn't on the remote (catches a
   forgotten tag push), and **"Latest" is computed, not chronological** — when backfilling
   several, create them oldest-first with `--latest=false` and pass `--latest` only on the newest, or
   the badge lands on whichever GitHub decides. Reversible: a Release can be deleted without touching
   the tag.

**`sync-test-repo.sh` RUNS ONLY WHEN EXPLICITLY ASKED FOR. It is not part of shipping, and "ship vX.Y.Z" is not a request for it.** It is a local, untracked TESTING convenience: it rsyncs `founder-skills/` into a SEPARATE and PUBLIC repo (`yaniv-golan/founderskills-test`) and pushes, so a build can be exercised in Cowork by hand. Nothing in the release depends on it and no user is waiting on it — users install from the marketplace clone that tracks `main`, so `plugin.json#version` on `main` is what they actually pick up (see VERSIONING.md).

It used to be numbered step 7 of the release, which read as "do this to finish shipping" and is wrong twice over: it publishes the working tree — not the tag — into a second public history, and it is a push to a repo the release process has no business touching unattended. If you do run it, run it only after the release gate is green: syncing a broken build means the manual test pass exercises a build you would never ship.

**Model-tier acceptance:** when adopting or recommending a new model tier, run the cap-table reliability bench (`evals/cap-table/run_reliability_bench.py`, see its `README.md`) and record the per-tier correctness; Sonnet 4.6 is the support floor. (The bench lives at repo-root `evals/` — outside the distributed `founder-skills/` plugin — so it isn't shipped to users, mounted into cowork runs, or folded into the cassette staleness hash.)

**Already-distributed retag pitfall:** a version is distributed once `main` carries it — the marketplace clone tracks `main`, so the push in step 6 ships it whether or not the tag run publishes a Release; keep its tag (step 6 says why). The same holds if you had separately run `sync-test-repo.sh` before noticing the bug. Either way, **bump to the next patch version instead of retagging** — Cowork caches by `plugin.json#version`, so retagging the same version will not refresh user caches (`cpd refresh ... --force-fetch -y` is the manual recovery, not always coordinatable across users).

