#!/bin/sh
# PreToolUse hook wrapper for Agent/Task dispatches: POSIX sh, for the same reason as
# stop-handover-check.sh (host-native on macOS at hostloop, dash in the Cowork VM). Fails open when
# there is no python3 -- the hooks enforce, the skill never depends on them.
command -v python3 >/dev/null 2>&1 || exit 0
f="$(dirname "$0")/pretooluse_dispatch.py"
# A missing body (a partial install) fails open too: exec on a missing file exits 2, which a
# PreToolUse hook reads as a block.
[ -f "$f" ] || { echo "founder-skills pretooluse-dispatch: $f not found; check skipped" >&2; exit 0; }
exec python3 "$f"
