#!/usr/bin/env bash
# PostToolUse for Edit|Write: format, lint, typecheck the touched Python file, then run the tests
# related to it. That test run is what the Stop hook's default "last failed" scope relies on.
INPUT=$(cat)
PY=""; for c in python3 python "py -3"; do case "$(command -v "${c%% *}" 2>/dev/null)" in *WindowsApps*) continue;; esac; $c -c "import sys; sys.exit(sys.version_info[0] != 3)" >/dev/null 2>&1 && { PY="$c"; break; }; done  # skip the slow, non-functional Windows Store stubs
FILE=$(printf '%s' "$INPUT" | $PY -c 'import sys,json,os; p=json.load(sys.stdin).get("tool_input",{}).get("file_path",""); print(os.path.relpath(os.path.realpath(p), os.path.realpath(os.getcwd())).replace(os.sep,"/") if p else "")' 2>/dev/null)
case "$FILE" in *.py) ;; *) exit 0;; esac
command -v uv >/dev/null || exit 0
uv run ruff format "$FILE" >/dev/null 2>&1
OUT=$(uv run ruff check "$FILE" 2>&1) || { echo "Ruff findings in $FILE:"; echo "$OUT" | head -30; }
case "$FILE" in src/*) OUT=$(uv run mypy "$FILE" 2>&1) || { echo "mypy:"; echo "$OUT" | head -20; };; esac

# Related tests: a test file runs itself; a source file runs tests whose name contains its stem.
[ -d tests ] || exit 0
case "$FILE" in
  tests/*.py) case "$(basename "$FILE")" in test_*.py|*_test.py) TARGET="$FILE";; *) exit 0;; esac ;;
  src/*.py)   STEM=$(basename "$FILE" .py); [ "$STEM" = "__init__" ] && exit 0; TARGET="-k $STEM" ;;
  *) exit 0 ;;
esac
OUT=$(uv run pytest -q -x $TARGET 2>&1); RC=$?
[ "$RC" -eq 0 ] || [ "$RC" -eq 5 ] || { echo "Tests related to $FILE are failing:"; echo "$OUT" | grep -E "(FAILED|ERROR|assert|Error)" | head -15; }
exit 0
