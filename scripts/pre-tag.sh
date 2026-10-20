#!/usr/bin/env bash
# Release preflight: run every gate CI runs, plus the version parity CI can only check
# AFTER you push a tag — locally, before you push one.
#
# WHY THIS EXISTS. v0.6.0 and v0.7.0 both burned tags on failures a green `pytest` never
# covered; v0.7.0 took three tags. The release steps listed those gates in prose, and prose
# is not a control.
#
# WHY THE SLOW GATES RUN AT ONCE. Run one after another the gates took about 27 minutes, almost
# all of it the suite (about 11) and the mutation corpus (about 14), on a machine with cores to spare.
# The independent gates now start in the background (each with its own output file, and each mypy
# with its own cache folder, since concurrent runs over one cache can corrupt it), the suite runs
# across the cores with pytest-xdist, and the background results are printed after it, each in the
# order it was declared, so every gate still reports its own output and the summary is unchanged. `PRETAG_SERIAL=1` runs everything one after
# another, as it used to, for a run whose timing or interleaving is in doubt.
#
# WHY IT DOES NOT STOP AT THE FIRST FAILURE. ci.yml's steps run under `-e`, so the first
# failing step masks every later one — that is precisely how v0.7.0 burned two tags in
# sequence (a script error hid eight more in another directory). This runs ALL gates and
# reports every failure at once, so one local run tells you everything to fix.
#
# Usage:
#   ./scripts/pre-tag.sh              # gates only
#   ./scripts/pre-tag.sh v0.7.1       # gates + verify the tag matches both manifests
#
# The version-parity block is lifted from .github/workflows/skill-quality.yml, whose
# verify-branch-gate job runs the same check on tag push. Keeping the two in step is guarded by
# founder-skills/tests/test_pre_tag_covers_ci.py — if a gate is added to ci.yml and not
# here, that test fails.

set -uo pipefail
cd "$(dirname "$0")/.."

TAG="${1:-}"
FAILED=()
PASSED=0

run_gate() {
  local name="$1"; shift
  printf '\n\033[1m▶ %s\033[0m\n' "$name"
  if "$@"; then
    PASSED=$((PASSED + 1))
  else
    FAILED+=("$name")
    printf '\033[31m  ✗ %s FAILED (continuing — see the summary)\033[0m\n' "$name"
  fi
}

# A gate started in the background: its output goes to its own file, and `report_background`
# prints each in the order it was started and records it as `run_gate` would. Under PRETAG_SERIAL
# it is simply `run_gate`.
BG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/pre-tag.XXXXXX")"
trap 'rm -rf "$BG_DIR"' EXIT
BG_NAMES=()
bg_gate() {
  if [ -n "${PRETAG_SERIAL:-}" ]; then
    run_gate "$@"
    return
  fi
  local name="$1"; shift
  local i=${#BG_NAMES[@]}
  BG_NAMES+=("$name")
  ( "$@" >"$BG_DIR/$i.log" 2>&1; echo $? >"$BG_DIR/$i.rc" ) &
}
report_background() {
  wait
  local i rc
  for i in "${!BG_NAMES[@]}"; do
    printf '\n\033[1m▶ %s\033[0m\n' "${BG_NAMES[$i]}"
    cat "$BG_DIR/$i.log"
    rc="$(cat "$BG_DIR/$i.rc" 2>/dev/null || echo 1)"
    if [ "$rc" = "0" ]; then
      PASSED=$((PASSED + 1))
    else
      FAILED+=("${BG_NAMES[$i]}")
      printf '\033[31m  ✗ %s FAILED (continuing — see the summary)\033[0m\n' "${BG_NAMES[$i]}"
    fi
  done
}

# Worker counts. The two slow gates, the suite and the mutation corpus, run at the same time and split
# the cores between them (measured: about 865 and 1,665 CPU-seconds on 14 cores); everything else in the
# background is light. Each gets at least two workers.
CORES="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)"
MUT_WORKERS=$(( CORES / 2 > 2 ? CORES / 2 : 2 ))
SUITE_WORKERS=$(( CORES - MUT_WORKERS > 2 ? CORES - MUT_WORKERS : 2 ))
if [ -n "${PRETAG_SERIAL:-}" ]; then
  XDIST=()
  MUT_XDIST=()
else
  XDIST=(-n "$SUITE_WORKERS")
  MUT_XDIST=(-n "$MUT_WORKERS")
fi

# --- lint ---------------------------------------------------------------------------------
run_gate "ruff check"        uv run ruff check .
run_gate "ruff format"       uv run ruff format --check .

# --- typecheck ----------------------------------------------------------------------------
# Per-directory because skills share filenames (checklist.py, compose_report.py); mypy needs
# them separated. `founder-skills/tests/` is the one people forget — it is a CI gate too.
#
# Written out literally rather than looped over a skill list. A loop would be shorter and
# would introduce a SECOND list of skills to keep in step with ci.yml — and would defeat
# test_pre_tag_covers_ci.py, which greps for each ci.yml target path. (It caught exactly
# that when this file first used a loop.)
bg_gate  "mypy market-sizing" uv run mypy --cache-dir .mypy_cache/pre-tag-market-sizing founder-skills/skills/market-sizing/scripts/
bg_gate  "mypy deck-review" uv run mypy --cache-dir .mypy_cache/pre-tag-deck-review founder-skills/skills/deck-review/scripts/
bg_gate  "mypy ic-sim" uv run mypy --cache-dir .mypy_cache/pre-tag-ic-sim founder-skills/skills/ic-sim/scripts/
bg_gate  "mypy financial-model-review" uv run mypy --cache-dir .mypy_cache/pre-tag-financial-model-review founder-skills/skills/financial-model-review/scripts/
bg_gate  "mypy competitive-positioning" uv run mypy --cache-dir .mypy_cache/pre-tag-competitive-positioning founder-skills/skills/competitive-positioning/scripts/
bg_gate  "mypy cap-table" uv run mypy --cache-dir .mypy_cache/pre-tag-cap-table founder-skills/skills/cap-table/scripts/
bg_gate  "mypy tests" uv run mypy --cache-dir .mypy_cache/pre-tag-tests founder-skills/tests/
bg_gate  "mypy shared scripts" uv run mypy --cache-dir .mypy_cache/pre-tag-shared-scripts founder-skills/scripts/

# --- the plugin's script hashes (the dispatch-prompt hook checks the plugin against them) -----------
bg_gate  "script hashes"     uv run python founder-skills/scripts/script_hashes.py --check

# --- tests --------------------------------------------------------------------------------
bg_gate  "pytest evals"      uv run pytest evals/cap-table/ -q
# Needs its own invocation with `-m mutation`: the gate above passes an explicit `-m`, which
# OVERRIDES `addopts` entirely rather than adding to it, so `addopts` deselects nothing there —
# the `and not mutation` in that line is what excludes this lane, and it is excluded from a bare
# `pytest` by `addopts`. Without `-m mutation` here it collects nothing and reports green.
# About 14 minutes serial (51 mutants), about 3.5 across 10 workers: each worker copies the repo to its
# own temp dir, then injects its share of the named defects and re-runs the cap-table selection. Mirrors the `mutation-corpus` job in skill-quality.yml, which runs only on
# the dispatched release-branch run — i.e. after the branch is pushed, a paid round-trip later.
bg_gate  "mutation corpus"   uv run pytest founder-skills/tests/test_mutation_corpus.py -q -m mutation ${MUT_XDIST[@]+"${MUT_XDIST[@]}"}

# --- privacy ------------------------------------------------------------------------------
bg_gate  "privacy guard"     uv run python scripts/privacy_guard.py --tree --no-names
bg_gate  "privacy tests"     uv run pytest scripts/test_privacy_guard.py -q
# Maintainer-only (CI has no private lists, so it passes there): on a machine that has the private
# sources list, `founderskills.privacyLists` must be `required`, so a missing list fails a hook rather
# than turning its layers off. `optional` passes with its own line; exit 3 names the setter lines.
bg_gate  "privacy switch"    uv run python scripts/privacy_guard.py --check-switch

# --- plugin manifests ---------------------------------------------------------------------
if command -v claude >/dev/null 2>&1; then
  bg_gate  "plugin validate"   claude plugin validate founder-skills
  bg_gate  "marketplace validate" claude plugin validate .
else
  printf '\n\033[33m▶ plugin validate — SKIPPED (claude CLI not on PATH; CI still runs it)\033[0m\n'
fi

# --- the suite: in the foreground, across the cores, while the gates above run ---------------
run_gate "pytest"            uv run pytest founder-skills/tests/ -q -m "not e2e and not mutation" ${XDIST[@]+"${XDIST[@]}"}

report_background

# --- version parity (release-only; no ordinary-CI equivalent) ------------------------------
# CI checks this on tag push, which is too late: the tag already exists and must be deleted
# and re-pushed. Checking it here is the whole point of a PRE-tag script.
if [ -n "$TAG" ]; then
  printf '\n\033[1m▶ version parity\033[0m\n'
  BARE="${TAG#v}"
  PJ=$(python3 -c "import json;print(json.load(open('founder-skills/.claude-plugin/plugin.json'))['version'])")
  PY=$(grep -E '^version = ' pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/')
  echo "  tag:            $BARE"
  echo "  plugin.json:    $PJ"
  echo "  pyproject.toml: $PY"
  if [ "$BARE" != "$PJ" ] || [ "$BARE" != "$PY" ]; then
    FAILED+=("version parity")
    printf '\033[31m  ✗ version parity FAILED — bump both manifests before tagging\033[0m\n'
  else
    PASSED=$((PASSED + 1))
  fi
else
  printf '\n\033[33m▶ version parity — SKIPPED (pass a tag: ./scripts/pre-tag.sh v0.7.1)\033[0m\n'
fi

# --- scoring changes (release-only; a downstream contract) ---------------------------------
# The newest CHANGELOG section must carry `### Scoring changes`, naming each skill whose pinned
# scoring files changed since the previous tag ("None." when none did). With a tag, the newest
# section must also BE that version. skill-quality.yml's verify-branch-gate runs it on tag push; deliberately not in
# ci.yml, since it is about a release, not a PR.
if [ -n "$TAG" ]; then
  run_gate "scoring changes"   python3 .github/scripts/scoring_changes_check.py --tag "$TAG"
else
  run_gate "scoring changes"   python3 .github/scripts/scoring_changes_check.py
fi

# --- summary ------------------------------------------------------------------------------
printf '\n%s\n' "────────────────────────────────────────────────"
if [ ${#FAILED[@]} -eq 0 ]; then
  printf '\033[32m✓ %d gate(s) passed. Safe to tag.\033[0m\n' "$PASSED"
  exit 0
fi
printf '\033[31m✗ %d passed, %d FAILED:\033[0m\n' "$PASSED" "${#FAILED[@]}"
for f in "${FAILED[@]}"; do printf '    - %s\n' "$f"; done
printf '\nFix all of the above before tagging — CI stops at the first one, so tagging now\n'
printf 'costs one burned tag per failure.\n'
exit 1
