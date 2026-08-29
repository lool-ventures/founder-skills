#!/usr/bin/env bash
# Release preflight: run every gate CI runs, plus the version parity CI can only check
# AFTER you push a tag — locally, before you push one.
#
# WHY THIS EXISTS. v0.6.0 and v0.7.0 both burned tags on failures a green `pytest` never
# covered; v0.7.0 took three tags. The release steps listed those gates in prose, and prose
# is not a control.
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
# The version-parity block is lifted from .github/workflows/skill-quality.yml, which runs
# the same check on tag push. Keeping the two in step is guarded by
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
run_gate "mypy market-sizing"           uv run mypy founder-skills/skills/market-sizing/scripts/
run_gate "mypy deck-review"             uv run mypy founder-skills/skills/deck-review/scripts/
run_gate "mypy ic-sim"                  uv run mypy founder-skills/skills/ic-sim/scripts/
run_gate "mypy financial-model-review"  uv run mypy founder-skills/skills/financial-model-review/scripts/
run_gate "mypy competitive-positioning" uv run mypy founder-skills/skills/competitive-positioning/scripts/
run_gate "mypy cap-table"               uv run mypy founder-skills/skills/cap-table/scripts/
run_gate "mypy tests"                   uv run mypy founder-skills/tests/

# --- tests --------------------------------------------------------------------------------
run_gate "pytest"            uv run pytest founder-skills/tests/ -q -m "not e2e and not mutation"
run_gate "pytest evals"      uv run pytest evals/cap-table/ -q
# Deselected from the run above by `addopts`, so it needs its own invocation with `-m mutation`
# (without the flag it collects nothing and reports green). ~3 min: it copies the repo to a temp
# dir once, then injects each named defect and re-runs the cap-table selection. Mirrors the
# `mutation-corpus` job in
# skill-quality.yml, which fires on tag push — i.e. AFTER the tag exists, which is the wrong side
# of the decision this script is for.
run_gate "mutation corpus"   uv run pytest founder-skills/tests/test_mutation_corpus.py -q -m mutation

# --- privacy ------------------------------------------------------------------------------
run_gate "privacy guard"     uv run python scripts/privacy_guard.py --tree --no-names
run_gate "privacy tests"     uv run pytest scripts/test_privacy_guard.py -q

# --- plugin manifests ---------------------------------------------------------------------
if command -v claude >/dev/null 2>&1; then
  run_gate "plugin validate"   claude plugin validate founder-skills
  run_gate "marketplace validate" claude plugin validate .
else
  printf '\n\033[33m▶ plugin validate — SKIPPED (claude CLI not on PATH; CI still runs it)\033[0m\n'
fi

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
