# Changelog

## [Unreleased]

### Added
- `.github/workflows/test.yml`: the kit's first CI. On every pull request and push to `main` it runs
  `bash -n` over every shell script, compiles `kit.py`, and runs the hook tests on Linux, macOS and
  Windows (Git Bash), because the hooks run on all three and had only ever been run on one.
- `tests/test_block_dangerous_git.py`: the kit's first tests. Standard library only
  (`python -m unittest discover -s tests -v`); builds throwaway repositories and runs the hook the way
  `settings.json` does. Covers the three defects in #5, the bypass above, and every block that must not loosen.
- "Before you write" ladder in `engineering-principles.md`: does it need to exist, does it already exist here, stdlib, native platform, installed dependency, then the minimum. Explicitly never removes boundary validation, data-loss handling, security, accessibility, tests, or requested behaviour. Bug fixes now start by grepping every caller and fixing the shared code once.
- `defer: <ceiling>, <upgrade path>` comment convention for deliberate shortcuts. `/definition-of-done` check 11 lists every marker in the diff and fails on a marker missing either half; code-reviewer checks the same.
- `/simplify-review` skill: over-engineering-only review of the diff, a path, or the repo, with `delete:`, `stdlib:`, `native:`, `yagni:`, `shrink:` tags and a net line count. Applies nothing.
- code-reviewer step 5 produces the same delete list, reported in a new "Delete list" section.
- `.claude-plugin/` (plugin.json, hooks.json, marketplace.json) so the agents, skills, and hooks can be installed with `/plugin`. Rules, permissions, design tokens, kit.json, and profiles are not plugin-shippable and still come from `new-project.sh`. `lib.sh` now finds `kit.py` next to itself instead of under the project's `.claude/hooks`, so the guard hooks work from a plugin root too.
- `scripts/measure-rule.sh`: clones a project per run, runs `claude -p` headless with `--setting-sources project` so no user-level plugins leak in, and compares added lines, cost, turns, and time between the current kit and a candidate overlay (or bare Claude Code when no overlay is given).

### Fixed
- **`.env.example` is readable again.** The deny rule `Read(./.env.*)` also matched `.env.example`, the one file
  the secrets rule tells Claude to read. It is replaced by rules built from `*` and `?` only: `.env`, every
  `.env.<suffix>` of one to six characters or eight and more, and the seven-letter names `staging`, `secrets`,
  `private`, `testing`, `preview`, `release`, `default`, `develop`, `sandbox`, `backups`, `current`, `archive`,
  `encrypt`. Bracket negation was tried first and does not work: Claude Code's matcher reads `[!e]` and `[^e]` as
  literal characters, which left `.env.example` blocked and opened `.env.zz`. Ceiling: an unlisted seven-letter
  suffix is readable; add it to the list. `new-project.sh` now drops retired kit rules when it merges a
  project's `settings.json`, because the merge keeps existing rules and the old one would otherwise survive
  every refresh. `tests/test_env_deny_rules.py` covers both.
- The git safety hook did not follow a directory written the way Git Bash writes it (`/c/Users/x`,
  or Cygwin's `/cygdrive/c/...`). Native Windows Python does not know that spelling, so the target
  looked unknowable and the commit was judged against the project. `kit.py` translates it on Windows
  only. Found the first day the #5 fix was live; the tests had only used the `C:/` spelling.
- **The git safety hook judged the wrong repository and the wrong moment (#5).** The protected-branch
  check read the session project's HEAD whatever the command targeted, so a commit on a feature branch
  in a sibling repository was refused while the project sat on `main`, and `git checkout -b x && git
  commit` was refused because HEAD is read before the command runs. `kit.py commit-branches` now reads
  the command far enough to follow `cd <dir>`, `git -C <dir>` and an earlier `checkout`/`switch` in the
  same command, and the hook judges each commit against the branch it will land on. What it cannot
  follow is judged against the project's HEAD, as before.
- **A hole the same work found:** the old pattern wanted `git` and `commit` side by side, so
  `git -C . commit`, `git -c k=v commit` and `git --no-pager commit` on `main` were never checked at
  all. They are now. Text that only mentions a commit (`git log --grep`, an `echo`, a heredoc body,
  `git commit-graph`) no longer trips the check.
- **`lib.sh` lost `kit.py` after its own `cd`.** `KIT_LIB_DIR` was resolved from a relative
  `BASH_SOURCE` after changing to `CLAUDE_PROJECT_DIR`; when the two differed (the app moved the
  session, a worktree was removed) every guard hook failed closed on every Bash call with a message
  about Python. It is resolved first now, and the block message names the missing file.
- **Line endings.** `.gitattributes` (the kit's and the one given to projects) now sets `* text=auto eol=lf`,
  so a checkout is LF whatever `core.autocrlf` says, and `new-project.sh` strips CR from every text file
  it copies, from the kit and from a design pack. A CRLF checkout used to make every copied `.md`,
  `.json` and `.py` show as modified in an LF project until `git add` renormalised it.
- `new-project.sh` corrupted project names containing `&` (`sed` expands an unescaped `&` to the matched text) and passed the profile through unchecked. The name is escaped for `&`, `/`, and `\`, names with a newline are rejected up front, and the profile is checked against the fixed list `typescript | python | scripts`.

### Changed
- `engineering-principles.md` says the I/O edge interfaces are the one place a single-implementation interface is expected, and adds "no unrequested abstractions elsewhere". Ideas adapted from Ponytail (MIT), see README "Related work".

## [0.2.0] - 2026-09-16

Driven by applying the kit to its first polyglot repository (a TypeScript API plus a Python worker, with a
vendored Shopify theme and an app that already had its own palette). Every item below is something the
first apply got wrong or could not express.

### Added
- **`.claude/kit.json`**, project-owned: `packages` (profile + directory), `design.pack`, `design.exempt`,
  `protected_branches`. Written once by the script, read by every hook through `core/.claude/hooks/kit.py`.
  Missing file behaves exactly as v0.1.0 did (one package at the root, `main`/`master` protected).
- **Polyglot projects.** `new-project.sh typescript=services/api,python=workers/agent <dir>` names a profile
  per package. New core dispatchers `post-edit.sh` and `stop-tests.sh` find the package that owns the edited
  file (or has uncommitted changes) and run that profile's hook from the package directory. Profile hooks
  moved to `.claude/hooks/<profile>/`.
- **Design packs.** `design.pack` names a directory or git URL; the script overlays it onto `design/` on every
  run. `brand.css` is appended to `tokens.css` as an override block, `design-system.md` replaces the rule
  file, everything else (README, `logo/`) lands in `design/`. The applied pack and revision are recorded in
  `.claude/DESIGN_PACK`. The kit itself stays brand-free.
- **`design.exempt`**: path globs the hex-colour hook skips, for vendored themes and files that are
  themselves token sources. The hook's message now says so.
- **`protected_branches`** in kit.json replaces the hardcoded `main`/`master` in the git hook.
- `new-project.sh update <dir>` refreshes a project from its kit.json without restating the profiles.
- Python hooks run without uv: `python-env.sh` picks `uv run` (uv + `uv.lock`), else the package's or the
  project's `.venv`, else `python -m`; a tool missing from that environment is skipped instead of failing.
- TypeScript hooks read the package manager from the lockfile (pnpm, yarn, npm), find binaries in hoisted
  `node_modules/.bin`, prefer the package's `typecheck` script over a guessed `tsc -p .`, and fall back to the
  `test` script when Vitest is absent (node:test, Jest).
- `docs/STACK.md` is stitched from every profile in use when a project has more than one.

### Changed
- **CI is project-owned.** The script generates `.github/workflows/ci.yml` once, from per-profile job
  fragments (`profiles/<p>/ci-job.yml`, one job per package with `working-directory`), and never overwrites
  it. v0.1.0 replaced an existing project's workflow on every run.
- An existing `.gitignore` gets the kit's local-only entries appended once, behind a marker line, instead
  of being left untouched.
- `.nvmrc` / `.python-version` are created in each package directory, not only at the root.
- `.python-version` default is 3.13.
- Hooks share `lib.sh` (project root, Python lookup, `kit` helper) instead of repeating the Python probe.

### Removed
- Per-profile `settings.json` and `.github/workflows/ci.yml`; the core settings wire the dispatchers and the
  CI comes from `ci-job.yml` fragments.

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
