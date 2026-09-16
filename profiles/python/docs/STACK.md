# Stack: Python

For data analysis, Excel and report generation, automation, CLIs, and Claude skill or agent development.

| Concern | Tool |
|---|---|
| Runtime | Python 3.12+ (see `.python-version`) |
| Project and deps | `uv` with `pyproject.toml`; lockfile committed |
| Tests | pytest, pytest-cov, hypothesis for property tests where useful |
| Lint / format | Ruff (lint and format), mypy in strict mode |
| Data | pandas or polars; openpyxl for Excel output |
| CLI | Typer when a CLI is needed |
| Coverage floor | 85% lines on `src/`, enforced in CI |

## Commands

```bash
uv sync                          # install
uv run python -m <package>       # run
uv run pytest                    # tests
uv run pytest -x -q --lf         # TDD loop: stop on first failure, last failed first
uv run pytest --cov=src --cov-report=term-missing
uv run ruff check .              # lint
uv run ruff format .             # format
uv run ruff format --check .
uv run mypy src                  # types
uv run pip-audit                 # dependency vulnerabilities
```

`pyproject.toml` should keep Ruff and mypy on project code only. `.claude/` holds agent memory and hooks, `design/` holds kit-owned design tokens and the image checker; neither is yours to lint:

```toml
[tool.ruff]
src = ["src", "tests"]
extend-exclude = [".claude", "design"]
```

## Test scope in hooks

Two hooks run tests for you. After every edit, the PostToolUse hook runs the tests related to the file you touched (a test file runs itself; `src/foo.py` runs tests whose name contains `foo`). When Claude tries to end a turn, the Stop hook refuses if tests are red.

By default the Stop hook uses **last-failed** scope: it reruns only what pytest recorded as failing and passes if nothing is recorded. This stays fast on a large suite. To run the **full suite on every turn** instead, add to `.claude/settings.json` (or `.claude/settings.local.json` for just yourself):

```json
{ "env": { "KIT_TEST_SCOPE": "full" } }
```

For one piece of work only, run `/tdd <item> full`: the skill writes `full` to `.claude/test-scope` (gitignored), which the Stop hook honours until the skill removes it at Exit. The `settings.json` value, when set, wins over the file.

CI always runs the full suite with coverage regardless of this setting.

## Layout

```
src/<package>/
  __init__.py
  core/        pure logic, no I/O
  io/          file, network, database adapters
  cli.py       entry point
tests/
  unit/  integration/  fixtures/
docs/
pyproject.toml
```

## Conventions

- Type hints on every function signature. mypy strict passes.
- Pure functions in `core/`; everything that touches disk, network, or time lives in `io/` behind a small interface.
- pydantic models for any structured input (config, API payloads, file schemas).
- Tests use fixtures and factories; no shared mutable state. Name tests as sentences.
- Every CLI entry point has at least one subprocess test (`subprocess.run([sys.executable, "-m", "<package>", ...])`) that asserts exit code, stdout, and stderr, including a redirected or closed stdout. In-process runners such as Typer's `CliRunner` never see interpreter shutdown, stream flush errors, or the real exit code; an earlier project shipped two bugs that passed every in-process test.
- Excel output: openpyxl with explicit number formats; never write a float where money should be a Decimal.
- User-facing files (`.xlsx`, `.docx`, `.pptx`, PDF, HTML reports) follow `.claude/rules/design-system.md`: palette hex values, the kit typeface, any logo from `design/logo/`. Run `uv run --no-project --with pillow python design/check_logo_aspect.py <file>` on every deck or document before it leaves the project.
