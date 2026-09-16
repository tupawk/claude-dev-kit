#!/usr/bin/env bash
# Stop hook: Claude may not finish a turn with failing tests. Exit 2 keeps Claude working and shows why.
#
# Runs each package's profile hook, .claude/hooks/<profile>/stop-tests.sh, from the package directory,
# but only for packages with uncommitted changes. The profile hook receives:
#   KIT_TEST_SCOPE   "full" to run the whole suite, otherwise the profile's cheap default
#                    (pytest last-failed, vitest --changed). Set it under "env" in .claude/settings.json,
#                    or for one piece of work let `/tdd <item> full` write .claude/test-scope.
#   KIT_ROOT, KIT_PY as in post-edit.sh
INPUT=$(cat)
. "$(dirname "$0")/lib.sh"
[ -n "$KIT_PY" ] || exit 0
ACTIVE=$(printf '%s' "$INPUT" | $KIT_PY -c 'import sys,json; print(json.load(sys.stdin).get("stop_hook_active", False))' 2>/dev/null)
[ "$ACTIVE" = "True" ] && exit 0                 # already re-prompted once this turn; avoid a loop
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0
SCOPE="${KIT_TEST_SCOPE:-}"
[ -z "$SCOPE" ] && [ -f .claude/test-scope ] && SCOPE=$(tr -d '[:space:]' < .claude/test-scope)
FAILED=0
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
  ( cd "$PKGPATH" && KIT_TEST_SCOPE="$SCOPE" KIT_ROOT="$KIT_ROOT" KIT_PY="$KIT_PY" bash "$HOOK" ) || FAILED=1
done < <(kit packages 2>/dev/null)
[ "$FAILED" -eq 0 ] && exit 0
echo "Tests are failing. Fix them or report STATUS: BLOCKED with the failure. Do not skip or weaken tests." >&2
exit 2
