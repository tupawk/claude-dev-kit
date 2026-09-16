#!/usr/bin/env bash
# TypeScript stop check: exit 2 if this package's tests are red. Called by .claude/hooks/stop-tests.sh
# from the package directory, only when the package has uncommitted changes.
#
# KIT_TEST_SCOPE=full runs the package's "test" script. The default, changed, runs `vitest run --changed`
# (only the test files related to what changed since the last commit) when Vitest is installed; a
# package on another runner (node:test, Jest) has no related mode, so its "test" script runs in full.
. "$KIT_ROOT/.claude/hooks/node-env.sh"
[ -f package.json ] || exit 0
has_script test || exit 0
case "${KIT_TEST_SCOPE:-changed}" in
  full) OUT=$($PM test 2>&1) && exit 0 ;;
  *)    if VITEST=$(bin vitest); then OUT=$("$VITEST" run --changed --passWithNoTests 2>&1) && exit 0
        else OUT=$($PM test 2>&1) && exit 0; fi ;;
esac
echo "$PM test in $(pwd -P | sed "s|^$KIT_ROOT/*||;s|^$|.|"):" >&2
echo "$OUT" | grep -E "(FAIL|✗|×|not ok|Error|expected)" | head -25 >&2
exit 2
