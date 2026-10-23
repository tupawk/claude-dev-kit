#!/usr/bin/env bash
# Stop hook: Claude may not finish a turn with failing tests. Exit 2 keeps Claude working and shows why.
#
# Runs each package's profile hook, .claude/hooks/<profile>/stop-tests.sh, from the package directory,
# but only for packages with uncommitted changes. The profile hook receives:
#   KIT_TEST_SCOPE   "full" to run the whole suite, otherwise the profile's cheap default
#                    (pytest last-failed, vitest --changed). Set it under "env" in .claude/settings.json,
#                    or for one piece of work let `/tdd <item> full` write .claude/test-scope.
#   KIT_ROOT, KIT_PY as in post-edit.sh
#
# Each run goes through `kit stop-run`: one at a time per package, skipped when the same tree was
# already proven green in the same scope, and stopped with everything it started once KIT_STOP_BUDGET
# seconds (default 240) have passed since this hook began. Keep the budget under the hook's "timeout"
# in settings.json (300): past that Claude Code gives up on the hook but does not stop what it started.
INPUT=$(cat)
. "$(dirname "$0")/lib.sh"
[ -n "$KIT_PY" ] || exit 0
ACTIVE=$(printf '%s' "$INPUT" | $KIT_PY -c 'import sys,json; print(json.load(sys.stdin).get("stop_hook_active", False))' 2>/dev/null)
[ "$ACTIVE" = "True" ] && exit 0                 # already re-prompted once this turn; avoid a loop
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0
SCOPE="${KIT_TEST_SCOPE:-}"
[ -z "$SCOPE" ] && [ -f .claude/test-scope ] && SCOPE=$(tr -d '[:space:]' < .claude/test-scope)
BUDGET="${KIT_STOP_BUDGET:-240}"
case "$BUDGET" in ''|*[!0-9]*) BUDGET=240 ;; esac
DEADLINE=$(( $(date +%s) + BUDGET ))
SH="$BASH"                                       # stop-run starts it from a native Python on Windows
command -v cygpath >/dev/null 2>&1 && SH=$(cygpath -w "$BASH")
export KIT_TEST_SCOPE="$SCOPE" KIT_ROOT KIT_PY
FAILED=0
UNPROVEN=0
while IFS=$'\t' read -r PROFILE PKGPATH; do
  [ -n "$PROFILE" ] || continue
  HOOK="$KIT_ROOT/.claude/hooks/$PROFILE/stop-tests.sh"
  [ -f "$HOOK" ] || continue
  [ -d "$PKGPATH" ] || continue
  # Nothing changed in this package since the last commit: nothing to prove.
  if git diff --quiet HEAD -- "$PKGPATH" 2>/dev/null && git diff --quiet --cached -- "$PKGPATH" 2>/dev/null \
     && [ -z "$(git ls-files --others --exclude-standard -- "$PKGPATH")" ]; then
    continue
  fi
  kit stop-run "$PROFILE" "$PKGPATH" "$SCOPE" "$DEADLINE" "$SH" "$HOOK"
  case $? in
    0) ;;
    124) UNPROVEN=1
         echo "Tests in $PKGPATH did not finish within the Stop hook's ${BUDGET}s budget (KIT_STOP_BUDGET), so they are not proven green. The run was stopped." >&2 ;;
    *) FAILED=1 ;;
  esac
done < <(kit packages 2>/dev/null)
[ "$FAILED" -eq 0 ] && [ "$UNPROVEN" -eq 0 ] && exit 0
[ "$FAILED" -eq 1 ] && echo "Tests are failing. Fix them or report STATUS: BLOCKED with the failure. Do not skip or weaken tests." >&2
[ "$UNPROVEN" -eq 1 ] && echo "Run the suite yourself, in the background if it is long, and report the result. Do not call the work done until it is green." >&2
exit 2
