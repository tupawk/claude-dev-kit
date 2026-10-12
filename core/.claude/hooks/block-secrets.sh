#!/usr/bin/env bash
# PreToolUse hook for Edit, Write, MultiEdit and NotebookEdit. Blocks writes that look like they contain
# credentials, and any write to a .env file other than .env.example.
#
# The decision is kit.py's `guard-secrets`, which reads every field an edit writes (content,
# new_string, edits[].new_string, new_source) and never the text being replaced, so removing a leaked
# key is possible. Exit 2 blocks the write and returns stderr to Claude.
INPUT=$(cat)
. "$(dirname "$0")/lib.sh"
if [ -z "$KIT_PY" ] || [ ! -f "$KIT_LIB_DIR/kit.py" ]; then
  # Fail closed: a guardrail that cannot read its input must not wave the write through.
  echo "Blocked by the secrets hook: no working Python 3 on PATH, or kit.py missing beside lib.sh, so the tool input cannot be parsed. Fix the environment; do not bypass the hook." >&2; exit 2
fi
REASON=$(printf '%s' "$INPUT" | kit guard-secrets 2>/dev/null) || {
  echo "Blocked by the secrets hook: could not parse the tool input. Fix the environment; do not bypass the hook." >&2; exit 2
}
[ -z "$REASON" ] && exit 0
echo "Blocked by the secrets hook: $REASON. Use environment variables and .env.example instead." >&2
exit 2
