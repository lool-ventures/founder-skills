#!/bin/sh
# PreToolUse hook wrapper for Agent/Task dispatches: POSIX sh, for the same reason as
# stop-handover-check.sh (host-native on macOS at hostloop, dash in the Cowork VM). Fails open when
# there is no python3 -- the hooks enforce, the skill never depends on them.
command -v python3 >/dev/null 2>&1 || exit 0
exec python3 "$(dirname "$0")/pretooluse_dispatch.py"
