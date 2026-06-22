#!/usr/bin/env bash
# Batch re-record + verify the founder-skills cowork cassettes.
# LIVE lane: needs the staged Cowork agent ELF + Docker + tokens (paid, local/self-hosted only).
# Usage: cowork-tests/rerecord.sh [scenario-name ...]   # no args = every scenario
set -euo pipefail
cd "$(dirname "$0")"   # -> cowork-tests/

# --- preflight (fail loud; never fake a pass) ---
command -v cowork-harness >/dev/null || { echo "FATAL: cowork-harness not on PATH"; exit 1; }
# Normalize: extract bare semver even if the CLI ever prefixes its --version output.
# `|| true`: under `set -euo pipefail`, BSD/macOS grep exits 1 on no-match and would abort the
# substitution BEFORE the explicit guard below — keep the guard reachable (fail loud, not silent).
ver="$(cowork-harness --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
[ -n "$ver" ] || { echo "FATAL: could not parse cowork-harness version"; exit 1; }
echo "cowork-harness $ver"
major="${ver%%.*}"; minor="$(echo "$ver" | cut -d. -f2)"
{ [ "$major" -gt 0 ] || [ "$minor" -ge 8 ]; } || { echo "FATAL: need >=0.8.0 (have $ver)"; exit 1; }
: "${COWORK_AGENT_BINARY:?FATAL: set COWORK_AGENT_BINARY to the staged claude ELF (claude-code-vm/<ver>/claude)}"
[ -x "$COWORK_AGENT_BINARY" ] || { echo "FATAL: agent binary not executable: $COWORK_AGENT_BINARY"; exit 1; }
docker info >/dev/null 2>&1 || { echo "FATAL: Docker not running (live lane needs it)"; exit 1; }
# Run dir MUST live outside the mounted plugin tree (recursive-copy + hash pollution otherwise).
export COWORK_HARNESS_RUNS_DIR="${COWORK_HARNESS_RUNS_DIR:-/tmp/ct-cowork-runs}"
echo "runs dir: $COWORK_HARNESS_RUNS_DIR  (agent image must be :2 — rebuild via 'cowork-harness doctor --tier container')"

# --- select scenarios ---
scns=()
if [ "$#" -gt 0 ]; then scns=("$@"); else
  for f in scenarios/*.yaml; do scns+=("$(basename "$f" .yaml)"); done
fi
echo "re-recording: ${scns[*]}"

# --- record (synthetic data only — every scenario subject is fictional Cadence/Acmecorp) ---
# Per-cassette temp+mv so a mid-batch failure never leaves a half-written committed cassette.
recorded=()
for n in "${scns[@]}"; do
  [ -f "scenarios/$n.yaml" ] || { echo "FATAL: scenarios/$n.yaml not found"; exit 1; }
  echo "=== record $n ==="
  tmp="cassettes/.$n.cassette.json.tmp"
  cowork-harness record "scenarios/$n.yaml" --out "$tmp"   # set -e aborts the batch loud on failure
  mv -f "$tmp" "cassettes/$n.cassette.json"                # atomic swap only on success
  recorded+=("cassettes/$n.cassette.json")
done
# NOTE: if the batch aborts mid-way, earlier cassettes are already swapped — revert the partial set with
# `git checkout -- cowork-tests/cassettes/` and re-run, rather than committing a half-new working tree.

# --- verify with the SAME gates as CI, SCOPED to what we just recorded ---
# A subset run must NOT verify the whole dir: the un-refreshed cassettes are legitimately still stale
# and would staleness-fail the batch. Full run (no args) -> the dir; subset -> only the refreshed files.
source ./privacy-allowlist.sh
echo "=== lint ==="; cowork-harness lint scenarios/*.yaml          # scenario-level, cheap — always all
if [ "$#" -gt 0 ]; then targets=("${recorded[@]}"); else targets=("cassettes/"); fi
for t in "${targets[@]}"; do
  echo "=== privacy: $t ===";   cowork-harness verify-cassettes "$t" --skip-staleness "${ALLOW[@]}"
  echo "=== staleness: $t ==="; cowork-harness verify-cassettes "$t" --skip-privacy   # fresh post-record
  echo "=== replay: $t ===";    cowork-harness replay "$t" --output-format json \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);ok=d["ok"] and all(r["result"]=="success" for r in d["results"]);print("replay ok=",ok);sys.exit(0 if ok else 1)'
done
echo "DONE. Review 'git diff -- cowork-tests/cassettes/' (synthetic only) then commit by name."
