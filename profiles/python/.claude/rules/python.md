---
paths:
  - "**/*.py"
---
# Python rules

- Type hints everywhere, mypy strict. No `# type: ignore` without a reason comment. No `Any` in public signatures.
- Ruff decides style; do not argue with the formatter.
- Raise specific exceptions with context. Never bare `except:`. Never `except Exception: pass`.
- Dataclasses or pydantic for structured data, not dicts with string keys passed around.
- `pathlib.Path`, not string paths. `subprocess.run` with a list, never `shell=True`.
- Decimal for money. Timezone-aware datetimes only.
- Docstrings (Google style) on every public function, class, and module: purpose, args, returns, raises.
- pytest: fixtures in `conftest.py`, parametrize instead of loops, `tmp_path` for files, `monkeypatch` for env.
- CLI behaviour that a user would see (exit codes, stderr text, output to a pipe or a closed stdout) is tested with `subprocess.run` on the real entry point, not only with an in-process runner.
