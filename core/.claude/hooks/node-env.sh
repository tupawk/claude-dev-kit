#!/usr/bin/env bash
# Sourced by the typescript profile's hooks. Finds the package manager and the tool binaries.
#
#   PM                 pnpm, yarn or npm, from the lockfile in the package or the project root
#   bin <tool>         prints the path of node_modules/.bin/<tool>, searching from the package up to the
#                      project root (hoisted workspaces); false when it is not installed
#   has_script <name>  true when package.json has that script
_lock_dir() { for d in . "$KIT_ROOT"; do for f in pnpm-lock.yaml yarn.lock package-lock.json; do [ -f "$d/$f" ] && { echo "$f"; return; }; done; done; }
case "$(_lock_dir)" in
  pnpm-lock.yaml) PM=pnpm ;;
  yarn.lock)      PM=yarn ;;
  *)              PM=npm ;;
esac
bin() {
  local d; d=$(pwd -P)
  while :; do
    [ -x "$d/node_modules/.bin/$1" ] && { echo "$d/node_modules/.bin/$1"; return 0; }
    [ "$d" = "$KIT_ROOT" ] || [ "$d" = "/" ] || [ "$d" = "$(dirname "$d")" ] && return 1
    d=$(dirname "$d")
  done
}
has_script() {
  [ -f package.json ] || return 1
  # shellcheck disable=SC2086
  $KIT_PY -c 'import json,sys; sys.exit(0 if sys.argv[1] in json.load(open("package.json")).get("scripts",{}) else 1)' "$1" 2>/dev/null
}
