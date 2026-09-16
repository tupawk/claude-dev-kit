#!/usr/bin/env bash
INPUT=$(cat)
PY=""; for c in python3 python "py -3"; do case "$(command -v "${c%% *}" 2>/dev/null)" in *WindowsApps*) continue;; esac; $c -c "import sys; sys.exit(sys.version_info[0] != 3)" >/dev/null 2>&1 && { PY="$c"; break; }; done  # skip the slow, non-functional Windows Store stubs
FILE=$(printf '%s' "$INPUT" | $PY -c 'import sys,json; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null)
case "$FILE" in *.py) ;; *) exit 0;; esac
command -v uv >/dev/null || exit 0
uv run ruff format "$FILE" >/dev/null 2>&1
OUT=$(uv run ruff check "$FILE" 2>&1) || { echo "Ruff findings in $FILE:"; echo "$OUT" | head -20; }
exit 0
