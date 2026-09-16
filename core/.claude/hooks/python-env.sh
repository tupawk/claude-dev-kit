#!/usr/bin/env bash
# Sourced by the python profile's hooks. Picks the environment that owns this package's tools.
#
#   run <tool> [args]   run a Python tool (ruff, mypy, pytest, ...) in the package's environment
#   has <tool>          true when that tool is installed there
#
# Order: uv when both uv and a uv.lock are present; else the package's .venv, else the project's .venv;
# else the Python on PATH with `-m`. `python -m ruff` works because ruff, mypy and pytest all ship a
# __main__; anything else you add here must too.
_venv_python() {
  for d in . "$KIT_ROOT"; do
    [ -x "$d/.venv/bin/python" ] && { echo "$d/.venv/bin/python"; return; }
    [ -x "$d/.venv/Scripts/python.exe" ] && { echo "$d/.venv/Scripts/python.exe"; return; }
  done
}
if command -v uv >/dev/null 2>&1 && [ -f uv.lock ]; then
  run() { uv run "$@"; }
else
  _PY=$(_venv_python)
  # shellcheck disable=SC2086  # KIT_PY may be the two-word "py -3"
  if [ -n "$_PY" ]; then run() { "$_PY" -m "$@"; }; else run() { $KIT_PY -m "$@"; }; fi
fi
has() { run "$1" --version >/dev/null 2>&1; }
