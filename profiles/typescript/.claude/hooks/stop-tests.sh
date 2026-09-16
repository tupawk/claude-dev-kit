#!/usr/bin/env bash
# Stop hook: Claude may not finish a turn with failing tests. Exit 2 keeps Claude working and shows why.
#
# Test scope (KIT_TEST_SCOPE under "env" in .claude/settings.json, else the file .claude/test-scope,
# which `/tdd full` writes for the duration of one plan item):
#   changed (default) run only the Vitest files related to files changed since the last commit.
#           The PostToolUse hook already ran the tests related to each edited file.
#   full    run the whole suite on every turn. Slower, stricter.
INPUT=$(cat)
PY=""; for c in python3 python "py -3"; do case "$(command -v "${c%% *}" 2>/dev/null)" in *WindowsApps*) continue;; esac; $c -c "import sys; sys.exit(sys.version_info[0] != 3)" >/dev/null 2>&1 && { PY="$c"; break; }; done  # skip the slow, non-functional Windows Store stubs
ACTIVE=$(printf '%s' "$INPUT" | $PY -c 'import sys,json; print(json.load(sys.stdin).get("stop_hook_active", False))' 2>/dev/null)
[ "$ACTIVE" = "True" ] && exit 0            # already re-prompted once this turn; avoid a loop
[ -f package.json ] || exit 0
git diff --quiet HEAD -- . 2>/dev/null && git diff --quiet --cached 2>/dev/null && exit 0   # nothing changed this turn
grep -q '"test"' package.json || exit 0
SCOPE="${KIT_TEST_SCOPE:-}"
[ -z "$SCOPE" ] && [ -f .claude/test-scope ] && SCOPE=$(tr -d '[:space:]' < .claude/test-scope)   # written by /tdd full
case "${SCOPE:-changed}" in
  full) OUT=$(pnpm test --run 2>&1) && exit 0 ;;
  *)    [ -f node_modules/.bin/vitest ] || exit 0
        OUT=$(node_modules/.bin/vitest run --changed --passWithNoTests 2>&1) && exit 0 ;;
esac
echo "Tests are failing. Fix them or report STATUS: BLOCKED with the failure. Do not skip or weaken tests." >&2
echo "$OUT" | grep -E "(FAIL|✗|×|Error|expected)" | head -25 >&2
exit 2
