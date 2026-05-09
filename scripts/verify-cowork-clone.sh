#!/usr/bin/env bash
# Verify the Cowork marketplace clone advanced to the upstream HEAD.
#
# Mitigates the silent-marketplace-refresh trap (Desktop architecture
# gist item 13): refresh can return success and bump lastUpdated even
# when the local clone's git HEAD didn't move.
#
# macOS-only — Cowork session state lives under
# ~/Library/Application Support/Claude/, which is a macOS-specific path.
#
# Bash 3.2-compatible (no mapfile, no associative arrays) so it works
# under macOS's default /bin/bash without requiring Homebrew bash.
#
# Usage:
#   ./scripts/verify-cowork-clone.sh <marketplace-name> [<remote-ref>]
#
# Example:
#   ./scripts/verify-cowork-clone.sh lool-founder-skills main
#
# Workflow context:
#   This script is intentionally manual. Cowork's Refresh action is async
#   and user-triggered — there is no event the script could hook into to
#   run automatically. Run this AFTER clicking Refresh in the Cowork UI.
#   Calling it from sync-test-repo.sh would just check pre-refresh state.
#
# Exit codes:
#   0 = all clones in sync (or marketplace is non-git source — nothing to check)
#   1 = at least one clone is stale; fix command printed for each
#   2 = misconfiguration (no marketplace dir found, or running on non-macOS)

set -euo pipefail

if [[ "$(uname)" != "Darwin" ]]; then
  echo "verify-cowork-clone.sh is macOS-only (Cowork's state path is platform-specific)" >&2
  exit 2
fi

MARKETPLACE="${1:?usage: $0 <marketplace-name> [<remote-ref>]}"
REMOTE_REF="${2:-main}"

BASE="$HOME/Library/Application Support/Claude/local-agent-mode-sessions"

# Warn-don't-fail if jq is missing — the gitCommitSha cross-check
# silently no-ops without it, which defeats the entire purpose of
# this script's defense-in-depth.
HAS_JQ=1
if ! command -v jq >/dev/null 2>&1; then
  echo "[warn] jq not installed — installed_plugins.json gitCommitSha cross-check will be skipped." >&2
  echo "[warn] Install with: brew install jq" >&2
  HAS_JQ=0
fi

# First find every marketplace dir (regardless of source type), so we can
# distinguish "non-git source — nothing to verify" from "no clone at all".
# Use a portable while-read loop instead of mapfile (bash 4+).
MARKETPLACE_DIRS=()
while IFS= read -r line; do
  MARKETPLACE_DIRS+=("$line")
done < <(find "$BASE" -type d -path "*/cowork_plugins/marketplaces/$MARKETPLACE" 2>/dev/null)

if [[ ${#MARKETPLACE_DIRS[@]} -eq 0 ]]; then
  echo "No Cowork install of marketplace '$MARKETPLACE' found under $BASE" >&2
  echo "Has it been added in Cowork yet?" >&2
  exit 2
fi

drift=0
for mp_dir in "${MARKETPLACE_DIRS[@]}"; do
  echo "Marketplace dir: $mp_dir"
  if [[ ! -d "$mp_dir/.git" ]]; then
    echo "  STATUS: not a git source (no .git/) — nothing to verify"
    echo
    continue
  fi

  local_sha=$(git -C "$mp_dir" rev-parse HEAD)
  remote_sha=$(git -C "$mp_dir" ls-remote origin "$REMOTE_REF" | awk '{print $1}')

  echo "  local : $local_sha"
  echo "  remote: $remote_sha"

  if [[ "$local_sha" != "$remote_sha" ]]; then
    echo "  STATUS: STALE — clone did not advance"
    echo "  Fix: git -C \"$mp_dir\" fetch origin && git -C \"$mp_dir\" reset --hard origin/$REMOTE_REF"
    drift=1
  else
    echo "  STATUS: clone matches upstream"
  fi

  # Cross-check: installed_plugins.json may pin an older gitCommitSha
  # than the clone HEAD. Even when the clone advanced, the install
  # snapshot in cowork_plugins/cache/ stays at the pinned commit until
  # the user runs Update. This handles BOTH installed_plugins.json
  # schema versions: v1 stores the entry as a single object, v2 as an
  # array (the CLI migrates v1→v2 on read; Desktop's reader does not).
  #
  # Caveat: in v2 schema, a plugin can have multiple installs across
  # scopes (user/project/local/managed). We pick [0] which is typically
  # the user-scope install — sufficient for our single-machine dev
  # workflow. If you have multi-scope installs, results may not reflect
  # every scope's freshness.
  cowork_root="${mp_dir%/marketplaces/*}"
  installed_json="$cowork_root/installed_plugins.json"
  if [[ "$HAS_JQ" -eq 1 && -f "$installed_json" ]]; then
    pinned=$(jq -r --arg mp "$MARKETPLACE" '
      .plugins // {} | to_entries[]
      | select(.key | endswith("@" + $mp))
      | .value
      | (if type == "array" then .[0] else . end)
      | .gitCommitSha // empty
    ' "$installed_json" 2>/dev/null || true)
    if [[ -n "$pinned" && "$pinned" != "$local_sha" ]]; then
      echo "  installed_plugins.json gitCommitSha: $pinned (≠ clone HEAD)"
      echo "  Hint: the install snapshot is older than the clone — run 'Update plugin' in Cowork."
    fi
  fi

  echo
done

exit "$drift"
