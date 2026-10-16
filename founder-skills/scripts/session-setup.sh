#!/bin/sh
# SessionStart hook: POSIX sh, because it runs host-native on macOS at hostloop and under dash in the
# Cowork VM. Every path exits 0: the hook informs, the skill never depends on it.
#
# 1. Persist CLAUDE_PLUGIN_ROOT into CLAUDE_ENV_FILE (single-quoted, so a path with any character
#    reads back the same when the file is sourced).
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  escaped=$(printf '%s' "$CLAUDE_PLUGIN_ROOT" | sed "s/'/'\\\\''/g")
  new_line="export CLAUDE_PLUGIN_ROOT='${escaped}'"
  # Remove any existing export line (exact anchor, not substring)
  if [ -f "$CLAUDE_ENV_FILE" ]; then
    tmp="${CLAUDE_ENV_FILE}.tmp.$$"
    grep -v '^export CLAUDE_PLUGIN_ROOT=' "$CLAUDE_ENV_FILE" > "$tmp" 2>/dev/null || true
    mv "$tmp" "$CLAUDE_ENV_FILE" 2>/dev/null || true
  fi
  # printf, never echo: dash's and macOS /bin/sh's echo read backslash escapes in the path.
  printf '%s\n' "$new_line" >> "$CLAUDE_ENV_FILE" 2>/dev/null || true
fi
# 2. After a compaction only, tell a run in progress to re-read its SKILL.md (compaction_reread.py).
#    The payload is tested here, so no other session start launches an interpreter. The match relies on
#    the runtime's compact JSON (no space after the colon), which every version measured writes.
payload=$(cat 2>/dev/null) || payload=""
case "$payload" in
  *'"source":"compact"'*)
    command -v python3 >/dev/null 2>&1 || exit 0
    f="$(dirname "$0")/compaction_reread.py"
    [ -f "$f" ] || { echo "founder-skills session-setup: $f not found; re-read note skipped" >&2; exit 0; }
    printf '%s' "$payload" | python3 "$f" || true
    ;;
esac
exit 0
