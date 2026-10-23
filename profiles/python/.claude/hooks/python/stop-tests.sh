#!/usr/bin/env bash
# Python stop check: exit 2 if this package's tests are red. Called by .claude/hooks/stop-tests.sh from
# the package directory, only when the package has uncommitted changes.
#
# KIT_TEST_SCOPE=full runs the whole suite. The default, last-failed, reruns only what pytest recorded
# as failing on its last run and passes when nothing is recorded; the post-edit hook keeps that record
# current by running the tests related to each edited file. Cheap even on a large suite.
#
# Last-failed is bounded to the files that still hold a recorded failure: when none of the recorded
# failures is collected (the test was renamed or deleted), `pytest --lf` runs the WHOLE suite, and it
# never clears an entry it cannot collect. `kit lf-files` drops entries whose file is gone, and after a
# green run `kit lf-passed` drops what is left for the files that ran. With no record in this package
# (a pytest.ini further up keeps it elsewhere) pytest decides, as before.
. "$KIT_ROOT/.claude/hooks/python-env.sh"
[ -f pyproject.toml ] || exit 0
[ -d tests ] || exit 0
kit() { $KIT_PY "${KIT_LIB_DIR:-$KIT_ROOT/.claude/hooks}/kit.py" "$@"; }
case "${KIT_TEST_SCOPE:-lf}" in
  full) ARGS="-q -x" ;;
  *)    ARGS="-q -x --lf --lfnf=none"
        if FILES=$(kit lf-files); then
          [ -n "$FILES" ] || exit 0                     # nothing recorded: nothing to rerun
          while IFS= read -r f; do set -- "$@" "$f"; done <<< "$FILES"
        fi ;;
esac
has pytest || exit 0
# shellcheck disable=SC2086
OUT=$(run pytest $ARGS "$@" 2>&1); RC=$?
if [ "$RC" -eq 0 ] || [ "$RC" -eq 5 ]; then             # 5 = nothing to run
  [ $# -eq 0 ] || kit lf-passed "$@"
  exit 0
fi
echo "pytest in $(pwd -P | sed "s|^$KIT_ROOT/*||;s|^$|.|"):" >&2
echo "$OUT" | grep -E "(FAILED|ERROR|assert|Error)" | head -25 >&2
exit 2
