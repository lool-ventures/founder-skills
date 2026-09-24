#!/bin/sh
# Stop hook wrapper: POSIX sh, because it runs host-native on macOS at hostloop and under dash in
# the Cowork VM. Fails open when there is no python3 -- the hook enforces, the skill never depends
# on it. stdin (the hook payload) passes through to the script.
command -v python3 >/dev/null 2>&1 || exit 0
exec python3 "$(dirname "$0")/stop_handover_check.py"
