#!/usr/bin/env bash
# TypeScript post-edit: format and lint the touched file, typecheck the package, then run the Vitest
# files related to it. Called by .claude/hooks/post-edit.sh from the package directory with KIT_FILE
# relative to it.
#
# Tools are looked up in node_modules/.bin from the package upward to the project root, so hoisted
# workspaces work. The typecheck prefers the package's own "typecheck" script (it knows which tsconfigs
# matter) and falls back to `tsc --noEmit -p` on the nearest tsconfig.json. Without Vitest there is no
# related-tests mode; the Stop hook runs the package's "test" script instead.
. "$KIT_ROOT/.claude/hooks/node-env.sh"
FILE="${KIT_FILE:-}"
[ -n "$FILE" ] && [ -f "$FILE" ] || exit 0
case "$FILE" in
  *.ts|*.tsx|*.js|*.jsx|*.css|*.json|*.md)
    PRETTIER=$(bin prettier) && "$PRETTIER" --write "$FILE" >/dev/null 2>&1
    ;;
esac
case "$FILE" in *.ts|*.tsx) ;; *) exit 0;; esac

ESLINT=$(bin eslint) && { OUT=$("$ESLINT" "$FILE" 2>&1) || { echo "ESLint findings in $FILE:"; echo "$OUT" | tail -30; }; }

if has_script typecheck; then
  OUT=$($PM run typecheck 2>&1) || { echo "Type errors:"; echo "$OUT" | grep -E "error TS" | head -20; }
elif TSC=$(bin tsc); then
  DIR=$(dirname "$FILE")
  while [ ! -f "$DIR/tsconfig.json" ] && [ "$DIR" != "." ] && [ "$DIR" != "/" ]; do DIR=$(dirname "$DIR"); done
  [ -f "$DIR/tsconfig.json" ] && { OUT=$("$TSC" --noEmit -p "$DIR" 2>&1) || { echo "Type errors:"; echo "$OUT" | grep -E "error TS" | head -20; }; }
fi

VITEST=$(bin vitest) || exit 0
case "$FILE" in
  *.test.ts|*.test.tsx|*.spec.ts|*.spec.tsx) OUT=$("$VITEST" run "$FILE" 2>&1) ;;
  *) OUT=$("$VITEST" related "$FILE" --run --passWithNoTests 2>&1) ;;
esac || { echo "Tests related to $FILE are failing:"; echo "$OUT" | grep -E "(FAIL|✗|×|Error|expected)" | head -15; }
exit 0
