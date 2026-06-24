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
# Floor is >=0.12.0, not just any recent minor: 0.12.0 ships baseline Desktop 1.15200.0. A re-record on an
# older harness would capture the PRIOR baseline (1.14271.0) and be [stale] the instant it lands — the
# refresh would no-op its own purpose. Pin the floor to the baseline-carrying release.
major="${ver%%.*}"; minor="$(echo "$ver" | cut -d. -f2)"
{ [ "$major" -gt 0 ] || [ "$minor" -ge 12 ]; } || { echo "FATAL: need >=0.12.0 (have $ver)"; exit 1; }
: "${COWORK_AGENT_BINARY:?FATAL: set COWORK_AGENT_BINARY to the staged claude ELF (claude-code-vm/<ver>/claude)}"
[ -x "$COWORK_AGENT_BINARY" ] || { echo "FATAL: agent binary not executable: $COWORK_AGENT_BINARY"; exit 1; }
docker info >/dev/null 2>&1 || { echo "FATAL: Docker not running (live lane needs it)"; exit 1; }
# Run dir MUST live outside the mounted plugin tree (recursive-copy + hash pollution otherwise).
export COWORK_HARNESS_RUNS_DIR="${COWORK_HARNESS_RUNS_DIR:-/tmp/ct-cowork-runs}"
# 0.12.0 moved only the Desktop baseline (1.14271.0 → 1.15200.0); the agent ELF is UNCHANGED at 2.1.181,
# so the `:2` image still applies — no rebuild needed for the 0.10→0.12 upgrade, just re-record against the new baseline.
echo "runs dir: $COWORK_HARNESS_RUNS_DIR  (agent image must be :2 — rebuild via 'cowork-harness doctor --tier container')"

# --- select scenarios ---
scns=()
if [ "$#" -gt 0 ]; then scns=("$@"); else
  for f in scenarios/*.yaml; do scns+=("$(basename "$f" .yaml)"); done
fi
echo "re-recording: ${scns[*]}"

# Authoring a NEW cassette (or one whose gates are hard to pre-script)? Don't iterate THIS batch loop on
# paid records discovering gate phrasing. Use 0.10.0's live-decider flow to answer gates in one pass:
#   cowork-harness record scenarios/<new>.yaml --decider-llm --intent "…"   # a model answers the gates
#   cowork-harness record scenarios/<new>.yaml --decider-dir <fresh-dir>    # YOU answer in-band (gates/answer)
# Then lock the chosen answers into the scenario's `answers:` (cowork-harness verify-run confirms they still
# match the run's gates in ~1s — no paid re-record) and re-record HERE. This batch loop stays SCRIPTED-only
# on purpose: a live decider stamps the cassette `authoring.nonDeterministic`, and committed cassettes must
# be reproducible via this script without a decider.
#
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
echo "=== lint ==="; cowork-harness lint scenarios/                # 0.9.0: lint accepts a directory
if [ "$#" -gt 0 ]; then targets=("${recorded[@]}"); else targets=("cassettes/"); fi
for t in "${targets[@]}"; do
  echo "=== privacy: $t ===";   cowork-harness verify-cassettes "$t" --skip-staleness "${ALLOW[@]}"
  # Staleness is a HARD gate (0.9.0): the git-tracked boundary closed the fresh-cassette-stale
  # asymmetry (H9), so a just-recorded cassette passes its own staleness check — validated. A [stale]
  # here therefore means real drift (fileSigs names the file); fail loud. (CI keeps staleness WARN
  # because CI can't re-record; here we just did, so green is the correct expectation.)
  echo "=== staleness: $t ==="; cowork-harness verify-cassettes "$t" --skip-privacy
  echo "=== replay: $t ===";    cowork-harness replay "$t" --output-format json \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);ok=d["ok"] and all(r["result"]=="success" for r in d["results"]);print("replay ok=",ok);sys.exit(0 if ok else 1)'
done
echo "DONE. Review 'git diff -- cowork-tests/cassettes/' (synthetic only) then commit by name."
