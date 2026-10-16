#!/usr/bin/env bash
# PreToolUse hook for Bash. Blocks destructive git and shell commands, and commits that would land on a
# protected branch ("protected_branches" in .claude/kit.json; default main and master, and an empty
# list turns that one check off).
#
# The decision is kit.py's `guard-bash`, which reads the command as shell words rather than text: it
# sees `git push -uf` as a force push and a `grep` for "git reset --hard" as a grep. Exit 2 blocks the
# command and returns stderr to Claude.
INPUT=$(cat)
. "$(dirname "$0")/lib.sh"
block() { echo "Blocked by the git safety hook: $1. Stop and explain to the owner what you were trying to do." >&2; exit 2; }
if [ -z "$KIT_LIB_DIR" ] || [ ! -f "$KIT_LIB_DIR/kit.py" ]; then
  echo "Blocked by the git safety hook: kit.py was not found next to lib.sh (looked in '${KIT_LIB_DIR:-?}'), so the tool input cannot be parsed. Fix the hook install; do not bypass the hook." >&2; exit 2
fi
if [ -z "$KIT_PY" ]; then
  # Fail closed: a guardrail that cannot read its input must not wave the command through.
  echo "Blocked by the git safety hook: no working Python 3 on PATH, so the tool input cannot be parsed. Fix the environment; do not bypass the hook." >&2; exit 2
fi
REASON=$(printf '%s' "$INPUT" | kit guard-bash 2>/dev/null) || {
  echo "Blocked by the git safety hook: could not parse the tool input. Fix the environment; do not bypass the hook." >&2; exit 2
}
[ -z "$REASON" ] || block "$REASON"
exit 0
