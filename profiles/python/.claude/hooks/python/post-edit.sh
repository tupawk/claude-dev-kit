#!/usr/bin/env bash
# Python post-edit: format, lint and typecheck the touched file, then run the tests related to it.
# Called by .claude/hooks/post-edit.sh from the package directory with KIT_FILE relative to it.
# That test run is what the Stop hook's default "last failed" scope relies on.
#
# Runner, in order: `uv run` when uv and a uv.lock are present; the package's .venv (or the project's);
# else the Python on PATH with `-m`. A tool that is not installed in that environment is skipped, so a
# project on plain pip and venv gets the same hook as one on uv.
. "$KIT_ROOT/.claude/hooks/python-env.sh"
FILE="${KIT_FILE:-}"
case "$FILE" in *.py) ;; *) exit 0;; esac
[ -f "$FILE" ] || exit 0

if has ruff; then
  run ruff format "$FILE" >/dev/null 2>&1
  OUT=$(run ruff check "$FILE" 2>&1) || { echo "Ruff findings in $FILE:"; echo "$OUT" | head -30; }
fi
case "$FILE" in src/*) has mypy && { OUT=$(run mypy "$FILE" 2>&1) || { echo "mypy:"; echo "$OUT" | head -20; }; };; esac

# Related tests: a test file runs itself; a source file runs tests whose name contains its stem.
[ -d tests ] || exit 0
has pytest || exit 0
case "$FILE" in
  tests/*.py) case "$(basename "$FILE")" in test_*.py|*_test.py) TARGET="$FILE";; *) exit 0;; esac ;;
  src/*.py)   STEM=$(basename "$FILE" .py); [ "$STEM" = "__init__" ] && exit 0; TARGET="-k $STEM" ;;
  *) exit 0 ;;
esac
# shellcheck disable=SC2086  # TARGET is deliberately two words when it is "-k <stem>"
OUT=$(run pytest -q -x $TARGET 2>&1); RC=$?
[ "$RC" -eq 0 ] || [ "$RC" -eq 5 ] || { echo "Tests related to $FILE are failing:"; echo "$OUT" | grep -E "(FAILED|ERROR|assert|Error)" | head -15; }
exit 0
