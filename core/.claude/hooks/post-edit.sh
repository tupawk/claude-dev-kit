#!/usr/bin/env bash
# PostToolUse for Edit|Write. Finds the package that owns the edited file (.claude/kit.json), then runs
# that profile's hook, .claude/hooks/<profile>/post-edit.sh, from the package directory with:
#   KIT_FILE   the edited file, relative to the package
#   KIT_ROOT   the project root
#   KIT_PY     a working Python 3
# A file outside every package, or a profile without a post-edit hook, is left alone.
INPUT=$(cat)
. "$(dirname "$0")/lib.sh"
[ -n "$KIT_PY" ] || exit 0                       # advisory hook: no Python, nothing to run
FILE=$(printf '%s' "$INPUT" | kit tool-input file_path 2>/dev/null)
REL=$(kit rel "$FILE" 2>/dev/null)
[ -n "$REL" ] || exit 0
PKG=$(kit package-for "$REL" 2>/dev/null)
[ -n "$PKG" ] || exit 0
PROFILE=${PKG%%$'\t'*}; PKGPATH=${PKG#*$'\t'}
HOOK="$KIT_ROOT/.claude/hooks/$PROFILE/post-edit.sh"
[ -n "$PROFILE" ] && [ -f "$HOOK" ] || exit 0
case "$PKGPATH" in .) KIT_FILE="$REL";; *) KIT_FILE="${REL#"$PKGPATH"/}";; esac
cd "$PKGPATH" && KIT_FILE="$KIT_FILE" KIT_ROOT="$KIT_ROOT" KIT_PY="$KIT_PY" bash "$HOOK"
exit 0
