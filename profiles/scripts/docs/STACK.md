# Stack: scripts and glue

For one-off utilities, connectors, and small internal tools. Lighter gates, same principles. Use Python unless the target environment is Node.

| Concern | Tool |
|---|---|
| Runtime | Python 3.12+ via `uv` (or Node LTS if required) |
| Tests | pytest, focused on the logic that would be painful to get wrong |
| Lint / format | Ruff |
| Coverage floor | None enforced, but every non-trivial function has at least one test |

## Commands

```bash
uv sync
uv run python <script>.py
uv run pytest -q
uv run ruff check . && uv run ruff format .
```

## Layout

```
scripts/        one file per tool, docstring at top says what it does and how to run it
lib/            shared helpers if two scripts need the same thing
tests/
README.md       one section per script: purpose, usage, example
```

## What "small" means here

`project_size: small` in CLAUDE.md. Plan is a short PLAN.md (or agreement in conversation for a single-file script). TDD still applies to logic. Security review still runs if the script touches credentials, external systems, or client data. Code review is optional. Docs: README section is mandatory.
