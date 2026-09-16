#!/usr/bin/env bash
# PreToolUse hook for Bash. Blocks destructive git and shell commands.
# Exit 2 blocks the command and returns stderr to Claude.
#
# The branches that refuse direct commits come from "protected_branches" in .claude/kit.json
# (default: main and master). An empty list turns that one check off; the kit recommends leaving it on.
INPUT=$(cat)
. "$(dirname "$0")/lib.sh"
if [ -z "$KIT_PY" ]; then
  # Fail closed: a guardrail that cannot read its input must not wave the command through.
  echo "Blocked by the git safety hook: no working Python 3 on PATH, so the tool input cannot be parsed. Fix the environment; do not bypass the hook." >&2; exit 2
fi
CMD=$(printf '%s' "$INPUT" | kit tool-input command 2>/dev/null) || CMD="__KIT_PARSE_ERROR__"
if [ "$CMD" = "__KIT_PARSE_ERROR__" ]; then
  echo "Blocked by the git safety hook: could not parse the tool input. Fix the environment; do not bypass the hook." >&2; exit 2
fi
[ -z "$CMD" ] && exit 0

block() { echo "Blocked by the git safety hook: $1. Stop and explain to the owner what you were trying to do." >&2; exit 2; }

# Split compound commands so a later segment (e.g. a jq expression with a '+') cannot trip a git pattern.
SEGS=$(printf '%s' "$CMD" | tr ';|&' '\n')
echo "$SEGS" | grep -Eq 'git\s+push\b.*\s(--force\S*|-f\b|\+\S+)' && block "force push"
echo "$CMD" | grep -Eq 'git\s+reset\s+--hard' && block "git reset --hard"
echo "$CMD" | grep -Eq 'git\s+(branch|push)\s+.*(-D|--delete)\s+main\b' && block "deleting main"
echo "$CMD" | grep -Eq 'git\s+checkout\s+--\s+\.' && block "discarding all working changes"
echo "$CMD" | grep -Eq 'git\s+clean\s+-[a-zA-Z]*f' && block "git clean -f"
echo "$CMD" | grep -Eq 'git\s+rebase\s+.*(-i|--interactive)' && block "interactive rebase (do it manually if needed)"
echo "$CMD" | grep -Eq 'rm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(/|~|\$HOME|\.\.)(\s|$)' && block "recursive delete of a root, home, or parent directory"

# Block commits while on a protected branch
if echo "$CMD" | grep -Eq 'git\s+commit'; then
  BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || git rev-parse --abbrev-ref HEAD 2>/dev/null)
  while read -r PROTECTED; do
    [ -n "$PROTECTED" ] && [ "$BRANCH" = "$PROTECTED" ] && block "committing directly to $BRANCH. Create a feature branch first"
  done < <(kit protected-branches 2>/dev/null)
fi
exit 0
