# CLAUDE.md

> This file is distilled: it keeps the rules and not the measurements behind them. **Those are NOT
> in git history** — `docs/internal/claude-md-archive/` holds the only copy of the pre-distillation
> file, untracked, on one disk. Read it when a rule here states a conclusion and you need what was
> measured to reach it; several were learned by a run that cost money. If that directory is gone, so
> is the reasoning. Cite nothing in this file by SHA: the history has been rewritten and pre-rewrite
> hashes do not resolve. Name the change and grep for the identifier.

The files under `.claude/rules/` are part of the same distilled set: the archive above holds the
measurements behind their rules too.

## Where the rest lives (read before the task)

Reference material lives in `.claude/rules/`. Each file attaches by itself when you open a file in its scope,
but a task that only runs git, gh, pytest or a search opens none, so Read the file first:

- Any release step, version bump, tag, CHANGELOG, harness version posture, cassette re-record:
  `.claude/rules/release.md`
- Deciding whether a PR needs a paid e2e dispatch: `.claude/rules/e2e-dispatch.md`
- Any `cowork-harness` command (`critique`, `record`, `replay`, `eval`, `verify-cassettes`, `lint`), the
  privacy allowlist, the corpus ceiling: `.claude/rules/cowork-harness.md`
- Any hook (SessionStart, Stop, PreToolUse, git hooks) or a module a hook loads: `.claude/rules/hooks.md`
- Editing a SKILL.md, an agent body or skill frontmatter: `.claude/rules/skill-md-conventions.md`
- What a file or test is for: `.claude/rules/repo-map.md`
- A shared script under `founder-skills/scripts/`: `.claude/rules/scripts-shared.md`
- A skill's scripts: `.claude/rules/scripts-deck-review.md`, `scripts-market-sizing.md`, `scripts-ic-sim.md`,
  `scripts-financial-model-review.md`, `scripts-cap-table.md`, `scripts-competitive-positioning.md`
- Installing, hot-patching or removing the plugin in Cowork, `--plugin-dir`: `.claude/rules/cowork-install.md`

New prose goes in the file for its topic, never here, unless it guards a destructive, public, paid or commit
action or applies to every task. CLAUDE.md and every file under `.claude/rules/` stay ≤ 38k chars
(`test_instruction_file_sizes`): a scoped file over the loader's limit is cut silently when it loads.

## Layout

- `founder-skills/` — the plugin: `skills/<skill>/` (each with `SKILL.md`, `scripts/`, `references/`),
  `agents/`, `scripts/` (shared scripts and the hook bodies), `data/` (generated, never hand-edited),
  `references/` (shared references and brand), `tests/`
- `scripts/` — repo tooling: `pre-tag.sh`, `privacy_guard.py`, the git hooks in `scripts/hooks/`
- `cowork-tests/` — cowork-harness scenarios, cassettes and the CI helpers that read them
- `evals/` — benches and corpora kept outside the shipped plugin
- `.github/` — workflows and the scripts they run
- `.claude/rules/` — the reference files listed above
- `docs/internal/` — design docs and notes; gitignored, never committed
- `artifacts/` — skill run output; gitignored

Full map, file by file: `.claude/rules/repo-map.md`.

## Plugin Structure

- `.claude-plugin/marketplace.json` — Marketplace manifest (root level)
- `founder-skills/.claude-plugin/plugin.json` — Plugin manifest with hooks
- marketplace.json carries `name`, a top-level `description` (shown to users; `claude plugin validate` warns without it), `owner` and `plugins` (each with `name`, `source`, `description`), the shape Anthropic's own catalogs use
- Do NOT add `version` or `metadata` fields to marketplace.json

## Script Conventions

- Scripts use PEP 723 inline metadata; default to `python`, `uv run` optional
- Scripts output JSON to stdout, warnings/errors to stderr
- All scripts support `--pretty` for human-readable output and `-o <file>` to write to file (skill scripts emit a JSON receipt to stdout confirming the write)
- Skill-local scripts live in `founder-skills/skills/<skill>/scripts/`
- **A producer that rejects its input MUST fail loudly: diagnostic to stdout, a line to stderr, `-o` left untouched, exit non-zero.** Six producers across four skills independently got this wrong — they wrote a `{"validation": {"status": "invalid"}}` stub *through* `-o` and returned 0, which both destroyed the prior good artifact and made every SKILL.md's "the pipe fails next" error branch unreachable; the only downstream signal was a *medium* warning naming a symptom. Use the `_fail_invalid` helper (canonical copy: `skills/market-sizing/scripts/market_sizing.py`). Stamp `metadata`/`graded_against` **before** calling it, so the diagnostic still carries provenance. `tests/test_skill_contract.py::test_producer_rejects_loudly_without_clobbering` runs each producer against a rejecting payload and asserts all three properties — deliberately behavioural, because the structural version ("must contain `_fail_invalid` or a `sys.exit(1)`") was measured **vacuous**: every one of these scripts already had `sys.exit(1)` for malformed-JSON errors. Add new producers to that registry. And no output may resolve to one of the script's own inputs: every writer with an output flag calls `_out_guard.refuse_output_onto_input` first, with every output it writes (`OUTPUT_IS_INPUT`, exit 1, nothing written). A new writer goes through it too: `test_out_guard_coverage.py` reds on an output flag that is neither passed to the guard nor exempt by `(script, flag)` with a reason, and the exemption map may only shrink. `insert_coaching.py` keeps its own, stricter guard.
- **The audit trail does not require clobbering, and a sidecar needs a downstream reader.** A producer may keep a rejected artifact beside the canonical one as `<canonical-filename>.rejected.json` (appended, so `competitor_verification.json.rejected.json` — not a replaced extension), leaving `-o` untouched. `verify_competitors.py` does this. **If it does, something downstream MUST key on the sidecar**: for an OPTIONAL artifact, absence otherwise reads as "the run skipped this step" and the deliverable presents unchecked analysis exactly as it presents checked analysis. Two ways for that signal to go missing, both measured here — key it on absence alone and a prior run's file silences it, so compare run_ids; and a *medium* code naming a symptom (`STALE_ARTIFACT`) is not the signal, because the founder needs the cause. `compose_report.py`'s `VERIFICATION_REJECTED` is high and does both.
- Compose scripts pair with it: a canonical artifact carrying `validation.status == "invalid"` raises `ARTIFACT_INVALID` (or `SIZING_INVALID` in market-sizing) at **high** severity, so it cannot be accepted away via `accepted_warnings`.

## Dev Setup

Install dev dependencies:

```bash
uv sync --extra dev
# or: pip install -e ".[dev]"
```

## Linting & Formatting

```bash
uv run ruff check .          # lint
uv run ruff format .         # auto-format
uv run ruff format --check . # check formatting without changes
```

## Type Checking

Scripts in different skills share filenames (`checklist.py`, `compose_report.py`), so mypy must be run per directory:

```bash
uv run mypy founder-skills/skills/market-sizing/scripts/
uv run mypy founder-skills/skills/deck-review/scripts/
uv run mypy founder-skills/skills/ic-sim/scripts/
uv run mypy founder-skills/skills/financial-model-review/scripts/
uv run mypy founder-skills/skills/competitive-positioning/scripts/
uv run mypy founder-skills/skills/cap-table/scripts/
uv run mypy founder-skills/tests/
uv run mypy founder-skills/scripts/
```

## Running Tests

```bash
uv run pytest                                       # all tests (e2e auto-skips without auth; cowork auto-skips without the harness CLI)
uv run pytest founder-skills/tests/ -v              # verbose
uv run pytest founder-skills/tests/ -v -m "not e2e and not mutation" # explicitly skip the paid + slow lanes
uv run pytest -m cowork                             # token-free cowork-harness cassette replay (needs `npm i -g cowork-harness@5.0.0` — exact, matching CI; no Docker/token)
uv run pytest -m mutation                           # curated mutant corpus (~14 min serial, ~3.5 across 10 workers, ~4.5 on half the cores beside the suite; deselected by default — see the WARNING below)
uv run pytest founder-skills/tests/ -q -m "not e2e and not mutation" -n auto  # the suite across the cores (pytest-xdist, a dev dependency): ~2 min instead of ~11
```

**`addopts` deselects `e2e` AND `mutation`, and a command-line `-m` OVERRIDES `addopts` rather than
adding to it.** So a bare `-m "not e2e"` silently RE-SELECTS the ~14-minute mutation corpus — and on a
working tree that is red for any unrelated reason it reports `THE NO-OP CONTROL FAILED`, which reads as
a break the contributor did not cause. Every explicit `-m` in this repo therefore says
`-m "not e2e and not mutation"`: `ci.yml`'s test job, `skill-quality.yml`'s contract-tests job,
`scripts/pre-tag.sh`, `CONTRIBUTING.md`, and the two invocations in this file. That list was wrong when
first written — it named three sites and this file itself disproved it six lines up. The mutation lane has its own `mutation-corpus` job (dispatch only) and its own
preflight gate; both must pass `-m mutation`, since naming the file alone collects nothing and reports green. `scripts/pre-tag.sh` runs the
suite and the mutation corpus at the same time, each across half the cores (`-n`), with the other gates
in the background, and prints every gate's output in a fixed order (about 5 minutes, against about 27 one
after another); `PRETAG_SERIAL=1` runs them one after another. The corpus re-proves its no-op control in
each worker's sandbox at teardown, so it runs the same serially and in parallel.

**After editing any plugin `.py` or agent body, run `python3 founder-skills/scripts/script_hashes.py --write`** (and commit `data/script-hashes.json` with the change) before the hook suites: they run the hook against this checkout, which then reads as a modified plugin; the modules that run it fail once with that command (`plugin_hashes_current` in `conftest.py`). After merging two branches that each changed plugin `.py` files, run the same one command and commit the manifest by name: a merge runs no pre-commit hook, so only the sync test notices.

**A skill's own test file is not what guards it.** `test_<skill>.py` covers the producers;
`test_<skill>_skill_contract.py` covers the SKILL.md / agent-body contracts, and there are
cross-cutting guards besides (`test_skill_contract.py` size ceilings, `test_cowork_invariants.py`
tool declarations, per-script suites like `test_backward_verifier.py`). Editing a SKILL.md or an
agent body and running only the matching `test_<skill>.py` reports green while the contract tests
fail. Run `-m "not e2e and not mutation"` before believing a skill change is done.

**Contract tests slice a fixed character window from an anchor** (`skill_text[start : start + N]`).
An additive edit to a dispatch template can push the tail past that boundary, so the test fails on
content that is still present. Prefer bounding on structure — the template's closing fence, the next
`##` heading — over widening N, which only defers the next break.

The `cowork` lane (`tests/test_cowork_cassette_replay.py`) replays the committed
`cowork-tests/cassettes/` through the harness's shipped pytest helper — deterministic,
no Docker or token. It is a **local-dev showcase**, not wired into `ci.yml` (the packaged
GitHub Action already replays in the `cowork-replay` workflow); it auto-skips when the
`cowork-harness` CLI is absent, so the default `uv run pytest` stays green on machines
without it.

The four e2e smokes drive the SDK against synthetic fixtures. Auth options (any one):

- `ANTHROPIC_API_KEY` env var (per-token API; ~$5-15/run)
- `CLAUDE_CODE_OAUTH_TOKEN` env var (subscription, long-lived token from `claude setup-token`)
- Local subscription auth: `claude /login` populates the macOS Keychain entry `Claude Code-credentials` (or `~/.claude/.credentials.json` on Linux/Windows)

For live progress during the e2e run (~5-20 min wall time), add `-s`:

```bash
uv run pytest founder-skills/tests/test_e2e_deck_review.py -v -m e2e --tb=short -s
```

Without `-s` the run looks silent (pytest captures stdout); with `-s` you see auth-detected, prompt, and per-message tool calls (`Bash`, `Read`, `Skill`, `Task`, etc.) as the SDK stream arrives.

The `e2e` marker keeps these tests out of the default per-PR `ci.yml` run; they execute only in the dedicated `skill-quality.yml` workflow.

## Internal Docs

- `docs/internal/` — Design docs and internal notes; never tracked or committed (gitignored)


## Committing (read before any `git commit`)

**Always commit with `git commit -s`.** This repo requires a DCO sign-off on every commit, and `DCO` is a required status check on `main` — an unsigned commit blocks any PR containing it. The `commit-msg` hook will reject an unsigned commit, but reaching that rejection means a wasted round-trip: pass `-s` the first time.

`-s` composes with everything, including the heredoc pattern used throughout this repo:

```bash
git commit -s -F - <<'EOF'
type(scope): subject
...
EOF
```

The trailer is appended to the existing trailer block, after `Co-Authored-By:` / `Claude-Session:`. Order within the block does not matter. To fix a commit already written: `git commit --amend -s`.

Historical note: 155 of the first 159 commits are unsigned, because `enforce_admins` is false on `main` and direct pushes bypass the required check. Do **not** retro-sign them — that would rewrite published history. The convention is that a DCO check only inspects the commits in a given PR, so existing history is grandfathered.

## Privacy Guard

`scripts/privacy_guard.py` blocks confidential-data leaks **without committing the names, figures or text it guards**. Six layers:

- **document** — confidential doc types (`.xlsx`/`.pdf`/`.docx`/…) tracked outside the synthetic-fixture allowlist (add a new legit fixture to `ALLOWLISTED_DOCS`). Name-free.
- **provenance** — the named-after-a-company antipattern triple: a proper-noun company name + a `P-#`/`R-#` round/case ID + a failure word, together (template `the <ProperNoun> <round/case-ID> <failure-word>`). High-precision; name-free.
- **name** — exact real names from `docs/internal/privacy-denylist.txt`, which is **git-ignored and never committed** (the detection logic ships; the names don't). List only distinctive names/phrases — never bare common-word names. CI runs `--tree --no-names` (layers 1+2 only; no name list present), so nothing is disclosed.

- **figure** (local only) — a figure the change ADDS ($ amounts, thousands-separated numbers, decimals, %, `x` multiples, integers of 3+ digits; whole-token, years/versions/UUID fragments and a minimal round-number list skipped) that also occurs in the local private sources and not in our own code at `origin/main`. Skips `cowork-tests/cassettes/` (generated recordings whose timings and counts collide by chance) and the synthetic replay corpus (`SYNTHETIC_CORPUS_FILES`, today only `evals/financial-model-review/metric_claim_corpus.json`): its harvest script admits only runs of tracked synthetic fixtures, and those runs are kept among the private sources, so its figures collide with themselves.
- **verbatim** (local only) — a 6-word run of added text found in the private sources and not in our code at `origin/main`. Until local commits are pushed, text we wrote since `origin/main` and later echoed in a run can also match; that noise shrinks as `origin/main` advances. A recording under `cowork-tests/cassettes/` (`RECORDING_PREFIXES`) is still scanned and still blocks, but only against the founder DOCUMENTS among the sources (`grams_inputs`): `.pdf`/`.csv`/`.docx`/`.pptx`/`.xlsx` anywhere, plus a `.md`/`.txt` whose own folder holds one and whose name carries none of our output names (`OUTPUT_NAME_MARKERS`). Kept run transcripts and reports repeat the skills' own prose and collided with every re-recorded lane; a document quoted into a tool result is the leak the layer exists for there. A recording line has its JSON escapes decoded first (a document's line break arrives as `\n`), and a run of six consecutive integers (line numbering, any width) is skipped on it. The synthetic replay corpus is matched the same way (documents only, escapes decoded); any other file under `evals/` is fully checked. `.docx`/`.pptx`/`.xlsx` are read with the stdlib (both sets); `.xls`/`.doc`/`.ppt` are skipped with a count on stderr.
- **figure-provenance** (everywhere) — a figure on a line that also names real data ("a live run", "the founder's", "from the data room", …; not "measured", which our own notes use constantly). Blocks locally, warns in CI (`--tree`); mark a reviewed synthetic line with `privacy-guard: synthetic`. Skips `cowork-tests/cassettes/`: recordings narrate synthetic runs in the skills' own words ("the founder's", "the deck's").

The private sources are folders listed in `docs/internal/privacy-private-sources.txt` (**git-ignored**; one path per line, `!<substring>` excludes copies of our own code; a relative root is read from the main checkout's root). All three lists are read from the MAIN checkout's `docs/internal/`, from a linked worktree too (`$FOUNDER_SKILLS_PRIVATE_DIR` first; cwd-relative only when no main checkout is found), and are edited only there: a worktree's own copy is never read, and one whose entries differ is noted with counts. A missing list turns its layer off, and in the hook modes (`--staged`, `--commit-msg`, `--range`) prints one line naming it (never the allowlist), which is normal on a public clone; with `founderskills.privacyLists=required` a missing list, an unresolvable main checkout or a worktree denylist/sources copy holding entries main lacks exits 3 instead (1 = findings, 2 = usage). `--tree` and explicit files are unchanged and silent. The index holds only hashes and is cached in `~/.cache/founder-skills/privacy-guard/`. Local false alarms go in `docs/internal/privacy-figure-allowlist.txt` (git-ignored: a committed allowlist would reveal that a public number equals a private one). Findings print path, line and the added token only, never the matching source or its text.

Scans: `--check-switch` (`pre-tag.sh`'s "privacy switch" gate: exit 3 when this machine has the sources list and the switch is unset; `optional` passes with its own line), `--staged` (pre-commit: whole staged files for layers 1-3, ADDED lines for 4-6), `--commit-msg FILE` (commit-msg hook, after the DCO check), `--range A..B` (added lines + commit messages; the `pre-push` hook runs it per pushed range), `--tree` (CI), and `--verbatim-report` with `--range`/`--staged` for per-file verbatim COUNTS (no text) when triaging; a recording's row adds its all-sources count beside the blocking one, so the collision with kept runs stays measured. Tests: `uv run pytest scripts/test_privacy_guard.py` (fake private folder built in `tmp_path`, invented figures only). CI enforces layers 1+2 and reports figure-provenance warnings in the `privacy` job.

## Guards (pushing, tagging, public repos, paid runs)

Each block below is copied word for word from the `.claude/rules/` file named above it, so it applies even
when that file is never opened. `test_claude_md_guards_match_source` holds every copy equal to its source:
edit both together.

From the opening of the release process in `.claude/rules/release.md`:

<!-- guard:push-main source:.claude/rules/release.md -->
**Pushing `main` ships.** Users install from the marketplace clone that tracks `main`, so the paid gate (`deck-review-e2e-smoke` and `mutation-corpus` in `.github/workflows/skill-quality.yml`) runs ONCE per release, on a `release/vX.Y.Z` branch BEFORE `main` moves, dispatched by hand. The tag push does not run it again: `verify-branch-gate` checks the tag against both `pyproject.toml` and `founder-skills/.claude-plugin/plugin.json` versions, checks the CHANGELOG's Scoring changes section, and finds the green dispatched run at the tagged commit (`.github/scripts/branch_gate_check.py`); then `publish-release` creates the GitHub Release. `scripts/pre-tag.sh vX.Y.Z` runs the version and Scoring checks locally first. Per-PR e2e is off by default; opt in via manual dispatch for architectural-surface PRs (list in `.claude/rules/e2e-dispatch.md`).
<!-- /guard -->

From the numbered release steps in `.claude/rules/release.md` (step 3):

<!-- guard:release-step-3 source:.claude/rules/release.md -->
3. `git commit -s -m "release: vX.Y.Z"`, then `scripts/pre-tag.sh vX.Y.Z`, which also checks the
   tag against both manifests and the Scoring changes section (a dispatched gate run skips both).
   Before anything leaves the machine: `main` must fast-forward from `origin/main`
   (`git fetch origin main && git merge-base --is-ancestor origin/main HEAD`; never `--force` to
   `main`), `python3 scripts/privacy_guard.py --tree --no-names` and `--range origin/main..HEAD` must
   be clean, and `git diff --stat origin/main..HEAD` must name nothing under `docs/internal/`,
   `docs/plans/` or `evals-local/`.
<!-- /guard -->

From step 5 (the paid gate on the release branch) in `.claude/rules/release.md`:

<!-- guard:release-step-5-rerun source:.claude/rules/release.md -->
   - A red lane: read the failing assertion before anything else. A re-run is PAID (the three lanes
     again), so re-run once only when the assertion reads as LLM variance; never re-run blind.
<!-- /guard -->

From step 5 in `.claude/rules/release.md`:

<!-- guard:release-step-5-failure source:.claude/rules/release.md -->
   - A real failure: the version has not shipped, so it needs no new bump. Put the fix below the
     release commit, so `release: vX.Y.Z` stays last (amend it in with `git commit --amend -s`, or
     commit it and rebase it under the release commit), add it to that version's CHANGELOG section,
     re-run `scripts/pre-tag.sh vX.Y.Z`, then
     `git push --force-with-lease origin HEAD:refs/heads/release/vX.Y.Z` and dispatch again. A lease
     refused with `(stale info)` means the local view of the branch is old: `git fetch origin
     release/vX.Y.Z` and push again. The bump-again rule in VERSIONING.md applies only once `main`
     carries the version.
<!-- /guard -->

From step 5 in `.claude/rules/release.md`:

<!-- guard:release-step-5-optin-deck source:.claude/rules/release.md -->
   - **The three opt-in deck-review lanes** (contradiction, numeric operators, image deck) run only on request:
     `gh workflow run skill-quality.yml --ref release/vX.Y.Z -f extra_deck_lanes=true`, a SEPARATE
     dispatch from the gate's (about $10-30 more). That run repeats the gate's lanes as well, and a red
     extra lane reds its job; `branch_gate_check.py` accepts any green dispatched run at the commit, so
     a red extra run does not block the tag once the plain gate run is green. Run them when the numeric
     chain or its proposer prompt changed. That dispatch also installs `tesseract-ocr` and `poppler-utils` for
     the image-deck lane (`RUN_PAID_E2E_OCR`), the only paid run that reaches Step 3.95; on it the market-sizing
     lane's scanned upload meets a real tesseract too, which is expected. Locally (billed, the tools on PATH):
     `RUN_PAID_E2E=1 RUN_PAID_E2E_OCR=1 uv run pytest founder-skills/tests/test_e2e_deck_review.py -k image_deck -v -m e2e --tb=short -s --basetemp /tmp/fs-e2e`.
<!-- /guard -->

From step 5 in `.claude/rules/release.md`:

<!-- guard:release-step-5-optin-fmr source:.claude/rules/release.md -->
   - **The opt-in financial-model-review unclassified-revenue-model lane** runs only on request:
     `gh workflow run skill-quality.yml --ref release/vX.Y.Z -f extra_lanes=true` (about $5-15), a
     separate dispatch from the gate's, with the same posture as the deck lanes above (the env
     `RUN_PAID_E2E_FMR_UNCLASSIFIED` is set from the input, never an `if:`; the lane is named in
     `ALLOWED_SKIPS`). It is a measurement: a red on its first assertion reports what the run wrote for
     `company.revenue_model_type` / `unclassified_reason`, not a regression. Locally (billed):
     `RUN_PAID_E2E=1 RUN_PAID_E2E_FMR_UNCLASSIFIED=1 uv run pytest founder-skills/tests/test_e2e_financial_model_review.py -k unclassified -v -m e2e --tb=short -s --basetemp /tmp/fs-e2e` (`--basetemp` OUTSIDE `~/.claude`).
<!-- /guard -->

From step 5 in `.claude/rules/release.md`:

<!-- guard:release-step-5-compaction source:.claude/rules/release.md -->
   - **The market-sizing compaction lane** (`test_market_sizing_compaction_lane`) is local only:
     `RUN_PAID_E2E_MS_COMPACTION` is never set by the workflow, and the lane is in `ALLOWED_SKIPS`. It sets
     `CLAUDE_CODE_AUTO_COMPACT_WINDOW` to the floor so the run compacts mid-way, writes
     `compaction_report.json` (C, R, F, as `_e2e_harness.compaction_report` defines them; written on a
     budget stop too), and asserts only that the run completed. It refuses to start without
     `RUN_PAID_E2E_MODEL` (a pinned model id) and caps each run with the SDK's `max_budget_usd`
     (`RUN_PAID_E2E_MAX_BUDGET_USD`, default 25). C is the main thread's own `compact_boundary`; a run
     without one placed in the stream fails as VOID, and is not a result.
<!-- /guard -->

From the numbered release steps in `.claude/rules/release.md` (step 6):

<!-- guard:release-step-6 source:.claude/rules/release.md -->
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
     (step 8 of `.claude/rules/release.md`).
   - A real failure (a wrong version or Scoring section): `main` already shipped this version. KEEP
     the tag — it marks what shipped — and let it stand with no Release; then release the next patch
     through these same steps. Deleting it breaks the next release: `scoring_changes_check.py` diffs
     from the tag of the previous CHANGELOG section and fails when that tag is missing. Never re-tag
     a version `main` has carried.
<!-- /guard -->

From the numbered release steps in `.claude/rules/release.md` (step 7):

<!-- guard:release-step-7 source:.claude/rules/release.md -->
7. **Delete the release branch if it still exists.** This repository is set to delete a merged PR's head branch (`delete_branch_on_merge`), and the PR is marked merged when its head reaches `main`, so it is usually gone already: `git ls-remote --exit-code origin refs/heads/release/vX.Y.Z && git push origin :release/vX.Y.Z`.
<!-- /guard -->

From the numbered release steps in `.claude/rules/release.md` (step 8, its opening):

<!-- guard:release-step-8 source:.claude/rules/release.md -->
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
<!-- /guard -->

From the end of the release process in `.claude/rules/release.md`:

<!-- guard:sync-test-repo source:.claude/rules/release.md -->
**`sync-test-repo.sh` RUNS ONLY WHEN EXPLICITLY ASKED FOR. It is not part of shipping, and "ship vX.Y.Z" is not a request for it.** It is a local, untracked TESTING convenience: it rsyncs `founder-skills/` into a SEPARATE and PUBLIC repo (`yaniv-golan/founderskills-test`) and pushes, so a build can be exercised in Cowork by hand. Nothing in the release depends on it and no user is waiting on it — users install from the marketplace clone that tracks `main`, so `plugin.json#version` on `main` is what they actually pick up (see VERSIONING.md).

It used to be numbered step 7 of the release, which read as "do this to finish shipping" and is wrong twice over: it publishes the working tree — not the tag — into a second public history, and it is a push to a repo the release process has no business touching unattended. If you do run it, run it only after the release gate is green: syncing a broken build means the manual test pass exercises a build you would never ship.
<!-- /guard -->

From the end of the release process in `.claude/rules/release.md`:

<!-- guard:retag source:.claude/rules/release.md -->
**Already-distributed retag pitfall:** a version is distributed once `main` carries it — the marketplace clone tracks `main`, so the push in step 6 of `.claude/rules/release.md` ships it whether or not the tag run publishes a Release; keep its tag (step 6 there says why). The same holds if you had separately run `sync-test-repo.sh` before noticing the bug. Either way, **bump to the next patch version instead of retagging** — Cowork caches by `plugin.json#version`, so retagging the same version will not refresh user caches (`cpd refresh ... --force-fetch -y` is the manual recovery, not always coordinatable across users).
<!-- /guard -->

From **Invoking** in `.claude/rules/cowork-harness.md`:

<!-- guard:harness-evaluator source:.claude/rules/cowork-harness.md -->
- Do NOT swap `--evaluator-model` on a fleet sweep. For document-analysis skills — every skill here — the task turn is ~61% of spend and the evaluator ~30%, so the saving is a third of its advertised size and it trades away the injection-resistance property verified for the default evaluator only. The levers are `--model` and probe scope. The default task-turn timeout is 30 min, which is NOT enough for market-sizing on a large corpus once the revision round runs: a 2026-09-24 run was killed mid-turn after two red-team rounds, produced no report, and was billed anyway. Pass `--timeout` for that shape. The report's `cost:` line prints the evaluator share.
<!-- /guard -->

From **Scenario and cassette tooling** in `.claude/rules/cowork-harness.md`:

<!-- guard:harness-run-dir source:.claude/rules/cowork-harness.md -->
- `--run-dir <fresh dir>` isolates a run's history, and with it disables `--max-budget-usd`: the cap prices from prior runs, and a fresh dir has none, so the run proceeds UNCAPPED. Never isolate a paid re-record that way.
<!-- /guard -->

From **Scenario and cassette tooling** in `.claude/rules/cowork-harness.md`:

<!-- guard:harness-eval source:.claude/rules/cowork-harness.md -->
- `eval` (4.2.0, EXPERIMENTAL upstream) runs two plugin versions interleaved and compares how often each assertion passes, and, since 4.9.0, the `metrics:` a scenario declares (a not-compared metric row exits 1, with no off-switch; none of ours declares one). Every eval is a paid run needing the owner's approval — there is no standing budget. It is never a CI gate or a routine step: most of our assertions pass near 100%, where a rise is undetectable and the smallest detectable drop at 5 reps is 80pp, so it would print "no detectable change" as unearned reassurance. Use it where it has power: a fix aimed at a lane whose pass rate sits between roughly 25% and 75% (the flaky lanes), or a content change once an assertion (e.g. `artifact_json` over a checklist) turns that change into pass/fail. Before spending, read the minimum detectable difference it prints while planning and stop if the expected effect is smaller. Pin concrete model ids; `--out` must be OUTSIDE a git work tree, while a `git:<ref>:<path>` arm needs the cwd INSIDE one; read `summary.erroredArms` before any row. `rerecord.sh` runs `prune --keep-last 5`, which trims eval runs too and leaves a report's run links dead (`eval report <dir>` still rebuilds it). A label is a signal to investigate, never proof.
<!-- /guard -->

From `.claude/rules/hooks.md` (the git hooks):

<!-- guard:git-hooks source:.claude/rules/hooks.md -->
- **pre-commit** (`scripts/hooks/pre-commit`): ruff format/lint on staged Python + the privacy-leak guard. Activate once per clone: `git config core.hooksPath scripts/hooks`. On a machine that has the private lists, also `git config --global founderskills.privacyLists required` and the same without `--global` in the main checkout (so a missing list fails a hook; `scripts/pre-tag.sh` checks it); a clone with hooks and no lists opts out with `git config founderskills.privacyLists optional`. All three privacy hooks run the guard beside the hook script (`scripts/hooks/../privacy_guard.py`; the work tree's own when none is there), so under this clone's absolute `core.hooksPath` every worktree runs the main checkout's guard. Bypass a confirmed false positive with `git commit --no-verify`.
- **commit-msg** (`scripts/hooks/commit-msg`): DCO gate — rejects a commit with no `Signed-off-by:` trailer matching the commit author. Validates only; it deliberately does not auto-append the trailer (a sign-off certifies that *you* have the right to submit, so a hook adding it silently would certify on your behalf). Then runs the privacy guard over the message (`--commit-msg`).
- **pre-push** (`scripts/hooks/pre-push`): the privacy guard over each pushed range's added lines and commit messages (`--range`), so a commit made with `--no-verify` is still checked before it leaves the machine.
<!-- /guard -->
