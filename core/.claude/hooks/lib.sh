#!/usr/bin/env bash
# Shared helpers for the kit's hooks. Sourced by every hook, never executed on its own.
#
#   KIT_ROOT   the project root (Claude Code runs hooks there; CLAUDE_PROJECT_DIR is authoritative)
#   KIT_PY     a working Python 3 command, skipping the Windows Store stubs on PATH
#   kit <cmd>  the config reader in kit.py (next to this file): packages, package-for, design-exempt, protected-branches,
#              rel, tool-input. See that file for what each prints.
#
# A guardrail hook (PreToolUse) must fail closed when KIT_PY is empty: a check that cannot read its
# input must not wave the action through. An advisory hook (PostToolUse, Stop) may exit 0 instead.
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || true
KIT_ROOT="$(pwd -P)"
KIT_PY=""
for c in python3 python "py -3"; do
  case "$(command -v "${c%% *}" 2>/dev/null)" in *WindowsApps*) continue;; esac
  $c -c "import sys; sys.exit(sys.version_info[0] != 3)" >/dev/null 2>&1 && { KIT_PY="$c"; break; }
done
# kit.py sits next to this file, so the hooks work both copied into a project and installed as a plugin.
KIT_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"; export KIT_LIB_DIR   # inline Python in hooks imports kit from here
kit() { $KIT_PY "$KIT_LIB_DIR/kit.py" "$@"; }
