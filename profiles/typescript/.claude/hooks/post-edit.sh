#!/usr/bin/env bash
# PostToolUse for Edit|Write: format and lint the touched file, typecheck, then run the Vitest files
# related to it. That test run is what the Stop hook's default "changed" scope builds on.
INPUT=$(cat)
PY=""; for c in python3 python "py -3"; do case "$(command -v "${c%% *}" 2>/dev/null)" in *WindowsApps*) continue;; esac; $c -c "import sys; sys.exit(sys.version_info[0] != 3)" >/dev/null 2>&1 && { PY="$c"; break; }; done  # skip the slow, non-functional Windows Store stubs
FILE=$(printf '%s' "$INPUT" | $PY -c 'import sys,json,os; p=json.load(sys.stdin).get("tool_input",{}).get("file_path",""); print(os.path.relpath(os.path.realpath(p), os.path.realpath(os.getcwd())).replace(os.sep,"/") if p else "")' 2>/dev/null)
case "$FILE" in
  *.ts|*.tsx|*.js|*.jsx|*.css|*.json|*.md)
    [ -f node_modules/.bin/prettier ] && node_modules/.bin/prettier --write "$FILE" >/dev/null 2>&1
    ;;
esac
case "$FILE" in
  *.ts|*.tsx)
    if [ -f node_modules/.bin/eslint ]; then
      OUT=$(node_modules/.bin/eslint "$FILE" 2>&1) || { echo "ESLint findings in $FILE:"; echo "$OUT" | tail -30; }
    fi
    if [ -f node_modules/.bin/tsc ]; then
      OUT=$(node_modules/.bin/tsc --noEmit -p . 2>&1) || { echo "Type errors:"; echo "$OUT" | grep -E "error TS" | head -20; }
    fi
    if [ -f node_modules/.bin/vitest ]; then
      case "$FILE" in
        *.test.ts|*.test.tsx|*.spec.ts|*.spec.tsx) OUT=$(node_modules/.bin/vitest run "$FILE" 2>&1) ;;
        *) OUT=$(node_modules/.bin/vitest related "$FILE" --run --passWithNoTests 2>&1) ;;
      esac || { echo "Tests related to $FILE are failing:"; echo "$OUT" | grep -E "(FAIL|✗|×|Error|expected)" | head -15; }
    fi
    ;;
esac
exit 0
