#!/usr/bin/env bash
# PreToolUse hook for Bash. Blocks destructive git and shell commands.
# Exit 2 blocks the command and returns stderr to Claude.
INPUT=$(cat)
PY=""; for c in python3 python "py -3"; do case "$(command -v "${c%% *}" 2>/dev/null)" in *WindowsApps*) continue;; esac; $c -c "import sys; sys.exit(sys.version_info[0] != 3)" >/dev/null 2>&1 && { PY="$c"; break; }; done  # skip the slow, non-functional Windows Store stubs
CMD=$(printf '%s' "$INPUT" | $PY -c 'import sys,json; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null) || CMD="__KIT_PARSE_ERROR__"
if [ "$CMD" = "__KIT_PARSE_ERROR__" ]; then
  # Fail closed: a guardrail that cannot read its input must not wave the command through.
  echo "Blocked by the git safety hook: could not parse the tool input (is a working Python 3 on PATH?). Fix the environment; do not bypass the hook." >&2; exit 2
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

# Block commits while on main
if echo "$CMD" | grep -Eq 'git\s+commit'; then
  BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || git rev-parse --abbrev-ref HEAD 2>/dev/null)
  [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ] && block "committing directly to $BRANCH. Create a feature branch first"
fi
exit 0
