#!/usr/bin/env bash
# Python stop check: exit 2 if this package's tests are red. Called by .claude/hooks/stop-tests.sh from
# the package directory, only when the package has uncommitted changes.
#
# KIT_TEST_SCOPE=full runs the whole suite. The default, last-failed, reruns only what pytest recorded
# as failing on its last run and passes when nothing is recorded; the post-edit hook keeps that record
# current by running the tests related to each edited file. Cheap even on a large suite.
. "$KIT_ROOT/.claude/hooks/python-env.sh"
[ -f pyproject.toml ] || exit 0
[ -d tests ] || exit 0
has pytest || exit 0
case "${KIT_TEST_SCOPE:-lf}" in
  full) ARGS="-q -x" ;;
  *)    ARGS="-q -x --lf --lfnf=none" ;;
esac
# shellcheck disable=SC2086
OUT=$(run pytest $ARGS 2>&1); RC=$?
if [ "$RC" -eq 0 ] || [ "$RC" -eq 5 ]; then exit 0; fi   # 5 = nothing to run
echo "pytest in $(pwd -P | sed "s|^$KIT_ROOT/*||;s|^$|.|"):" >&2
echo "$OUT" | grep -E "(FAILED|ERROR|assert|Error)" | head -25 >&2
exit 2
