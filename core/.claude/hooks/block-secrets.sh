#!/usr/bin/env bash
# PreToolUse hook for Edit and Write. Blocks writes that look like they contain credentials
# and any write to .env files.
INPUT=$(cat)
PY=""; for c in python3 python "py -3"; do case "$(command -v "${c%% *}" 2>/dev/null)" in *WindowsApps*) continue;; esac; $c -c "import sys; sys.exit(sys.version_info[0] != 3)" >/dev/null 2>&1 && { PY="$c"; break; }; done  # skip the slow, non-functional Windows Store stubs
eval "$(printf '%s' "$INPUT" | $PY -c '
import sys, json, shlex
d = json.load(sys.stdin)
ti = d.get("tool_input", {})
path = ti.get("file_path", "")
content = ti.get("content", "") or ti.get("new_string", "") or ""
print("FILE=" + shlex.quote(path))
print("CONTENT=" + shlex.quote(content))
print("KIT_PARSED=1")
' 2>/dev/null)"
if [ "${KIT_PARSED:-0}" != "1" ]; then
  # Fail closed: a guardrail that cannot read its input must not wave the write through.
  echo "Blocked by the secrets hook: could not parse the tool input (is a working Python 3 on PATH?). Fix the environment; do not bypass the hook." >&2; exit 2
fi

block() { echo "Blocked by the secrets hook: $1. Use environment variables and .env.example instead." >&2; exit 2; }

case "$FILE" in
  *.env|*/.env.*|.env.*) case "$FILE" in *.env.example) ;; *) block "writing to $FILE";; esac;;
esac

printf '%s' "$CONTENT" | grep -Eq 'AKIA[0-9A-Z]{16}' && block "AWS access key pattern"
printf '%s' "$CONTENT" | grep -Eq -- '-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----' && block "private key"
printf '%s' "$CONTENT" | grep -Eq 'sk-(ant-|live_|test_)?[A-Za-z0-9_-]{20,}' && block "API secret key pattern"
printf '%s' "$CONTENT" | grep -Eq 'gh[pousr]_[A-Za-z0-9]{30,}' && block "GitHub token"
printf '%s' "$CONTENT" | grep -Eq 'xox[abpr]-[A-Za-z0-9-]{10,}' && block "Slack token"
printf '%s' "$CONTENT" | grep -Eiq '(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*["'"'"'][^"'"'"'$<{]{12,}["'"'"']' && block "hardcoded credential assignment"
exit 0
