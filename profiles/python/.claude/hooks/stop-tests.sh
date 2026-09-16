#!/usr/bin/env bash
# Stop hook: Claude may not finish a turn with failing tests.
#
# Test scope (KIT_TEST_SCOPE under "env" in .claude/settings.json, else the file .claude/test-scope,
# which `/tdd full` writes for the duration of one plan item):
#   lf    (default) rerun only the tests pytest recorded as failing on its last run; if none are
#         recorded, pass. The PostToolUse hook runs the tests related to each edited file, which is
#         what keeps that record current. Cheap even on a large suite.
#   full  run the whole suite on every turn. Slower, stricter.
INPUT=$(cat)
PY=""; for c in python3 python "py -3"; do case "$(command -v "${c%% *}" 2>/dev/null)" in *WindowsApps*) continue;; esac; $c -c "import sys; sys.exit(sys.version_info[0] != 3)" >/dev/null 2>&1 && { PY="$c"; break; }; done  # skip the slow, non-functional Windows Store stubs
ACTIVE=$(printf '%s' "$INPUT" | $PY -c 'import sys,json; print(json.load(sys.stdin).get("stop_hook_active", False))' 2>/dev/null)
[ "$ACTIVE" = "True" ] && exit 0
[ -f pyproject.toml ] || exit 0
[ -d tests ] || exit 0
git diff --quiet HEAD -- . 2>/dev/null && git diff --quiet --cached 2>/dev/null && exit 0
command -v uv >/dev/null || exit 0
SCOPE="${KIT_TEST_SCOPE:-}"
[ -z "$SCOPE" ] && [ -f .claude/test-scope ] && SCOPE=$(tr -d '[:space:]' < .claude/test-scope)   # written by /tdd full
case "${SCOPE:-lf}" in
  full) ARGS="-q -x" ;;
  *)    ARGS="-q -x --lf --lfnf=none" ;;
esac
OUT=$(uv run pytest $ARGS 2>&1); RC=$?
[ "$RC" -eq 0 ] || [ "$RC" -eq 5 ] && exit 0   # 5 = nothing to run
echo "Tests are failing. Fix them or report STATUS: BLOCKED with the failure. Do not skip or weaken tests." >&2
echo "$OUT" | grep -E "(FAILED|ERROR|assert|Error)" | head -25 >&2
exit 2
