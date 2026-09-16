#!/usr/bin/env bash
# Scripts post-edit: format and lint the touched Python file. Lighter than the python profile: no
# typecheck, no test run. Called by .claude/hooks/post-edit.sh from the package directory.
. "$KIT_ROOT/.claude/hooks/python-env.sh"
FILE="${KIT_FILE:-}"
case "$FILE" in *.py) ;; *) exit 0;; esac
[ -f "$FILE" ] || exit 0
has ruff || exit 0
run ruff format "$FILE" >/dev/null 2>&1
OUT=$(run ruff check "$FILE" 2>&1) || { echo "Ruff findings in $FILE:"; echo "$OUT" | head -20; }
exit 0
