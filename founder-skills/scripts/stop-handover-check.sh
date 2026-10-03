#!/bin/sh
# Stop hook wrapper: POSIX sh, because it runs host-native on macOS at hostloop and under dash in
# the Cowork VM. Fails open when there is no python3 -- the hook enforces, the skill never depends
# on it. stdin (the hook payload) passes through to the script.
command -v python3 >/dev/null 2>&1 || exit 0
f="$(dirname "$0")/stop_handover_check.py"
# A missing body (a partial install) fails open too: exec on a missing file exits 2, which a
# hook reads as a block.
[ -f "$f" ] || { echo "founder-skills stop-handover-check: $f not found; check skipped" >&2; exit 0; }
exec python3 "$f"
