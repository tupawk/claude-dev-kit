# Changelog

## [0.1.0] - 2026-09-16

First public release. Ported from an internal, company-specific kit with every organisation-specific asset and instruction removed.

### Added
- Core: CLAUDE.md index, six Opus subagents (architect, implementer, test-writer, security-reviewer, code-reviewer, docs-writer), four skills (`/plan-project`, `/tdd`, `/definition-of-done`, `/update-docs`), rules (engineering principles, when-stuck, git workflow, documentation, secrets, design-system, path-scoped frontend), docs templates, PR template.
- Hooks, all failing closed when the tool input cannot be parsed:
  - `block-dangerous-git.sh`: force pushes, commits on `main`, history rewrites, branch deletion.
  - `block-secrets.sh`: common credential patterns in Edit and Write.
  - `block-hardcoded-colors.sh`: hex colour literals in frontend files; `design/` is exempt and a same-line `brand-exception:` comment is the escape hatch.
- `design/tokens.css` with a neutral placeholder palette (`--brand-*`), semantic roles (`--color-*`), type scale, spacing, radii, shadows, motion, a `.inverse` dark-surface variant, and `.btn`, `.display`, `.stat`, `.img-rounded`, `.logo` helpers. Measured contrast table and a contrast snippet in `design/README.md`.
- `design/check_logo_aspect.py`: flags stretched images in `.pptx` and `.docx` files; run with `uv run --no-project --with pillow`.
- Profiles: `typescript` (pnpm, Vitest, Playwright, ESLint, Prettier), `python` (uv, pytest, Ruff, mypy strict, subprocess tests for CLI entry points), `scripts` (lighter gates). Each has PostToolUse lint/format/typecheck hooks, a Stop hook that refuses to finish with red tests (last-failed scope by default, `KIT_TEST_SCOPE=full` or `/tdd <item> full` for the whole suite), CI workflow, and STACK.md.
- `scripts/new-project.sh` to assemble a project from core plus one profile, or refresh the kit-owned files in an existing project. Merges `settings.json`, records the kit tag in `.claude/KIT_VERSION`, skips the Windows Store Python stubs.
- `.gitattributes` keeping shell hooks LF on Windows checkouts.
