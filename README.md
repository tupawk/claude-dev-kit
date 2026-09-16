# claude-dev-kit

Reusable standards for building software with Claude Code. One core set of rules, agents, skills, and hooks, plus a small profile per stack. New projects start from it; existing projects pull updates from it. Nothing in here is tied to a company or a brand: the design tokens ship with a neutral placeholder palette you replace in one file.

## What is in here

```
core/                        stack-agnostic, every project gets all of this
  CLAUDE.md                  index of how we work (plan first, TDD, ask when stuck, DoD)
  .claude/agents/            six Opus subagents: architect, implementer, test-writer,
                             security-reviewer, code-reviewer, docs-writer
  .claude/skills/            /plan-project, /tdd, /definition-of-done, /update-docs
  .claude/rules/             engineering principles, when-stuck, git, docs, secrets,
                             design-system (always on), frontend (path-scoped)
  .claude/hooks/             block destructive git commands, secrets in writes, hex colours in frontend files
  .claude/settings.json      permissions and hook wiring
  design/tokens.css          design tokens, the only place colors and type are defined
  design/check_logo_aspect.py  flags stretched images in .pptx and .docx output
  docs/                      templates: ARCHITECTURE, PLAN, CHANGELOG, DECISIONS (ADRs)
  .github/                   PR template
profiles/
  typescript/                Next.js-style web apps: Vitest, Playwright, ESLint, Prettier, pnpm
  python/                    data, automation, CLIs, skills: uv, pytest, Ruff, mypy
  scripts/                   small utilities and glue, lighter gates
scripts/new-project.sh       assembles core + profile into a project, or updates one
```

## Create a new project

```bash
git clone git@github.com:tupawk/claude-dev-kit.git
claude-dev-kit/scripts/new-project.sh typescript ~/code/my-app "My App"
cd ~/code/my-app
# fill in Purpose and Owner in CLAUDE.md, set up the stack per docs/STACK.md, commit
claude
> /plan-project
```

## Update an existing project to the latest standards

```bash
cd claude-dev-kit && git pull
scripts/new-project.sh <profile> ~/code/existing-project
cd ~/code/existing-project && git diff .claude/ design/ docs/STACK.md
```

The script refreshes what the kit owns (`.claude/`, `design/`, `docs/STACK.md`, CI, PR template) and never touches what the project owns (`CLAUDE.md`, `README.md`, plan, architecture, code).

## Make the design tokens yours

`core/design/tokens.css` ships a neutral palette. Change the `--brand-*` values at the top of that file, re-measure contrast as described in `core/design/README.md`, update the hex table in `core/.claude/rules/design-system.md`, and optionally add logo files under `core/design/logo/`. The hook, rules, and Definition of Done all read from those files and need no edits.

## How the pieces fit

| Need | Mechanism | Where |
|---|---|---|
| Plan reviewed before code | `/plan-project` skill + `architect` agent + `Status: APPROVED` gate in PLAN.md | core |
| Opus for design, review, security | `model: opus` in each agent's frontmatter | core/.claude/agents |
| Engineering principles | rules loaded every session | core/.claude/rules |
| Ask when stuck, no workarounds | when-stuck rule; agents return `STATUS: BLOCKED` | core |
| TDD | `/tdd` skill + PostToolUse hook that runs the tests related to each edit + Stop hook that refuses to finish with red tests (last-failed scope by default, `KIT_TEST_SCOPE=full` for the whole suite; see the profile's STACK.md) | core + profile |
| Consistent, accessible UI | tokens.css + path-scoped frontend rule + PreToolUse hook that blocks hex colours outside tokens.css + image aspect checker | core |
| Git safety | PreToolUse hook + permission deny rules | core |
| Maintainable docs | documentation rule, `/update-docs`, `docs-writer`, PR template | core |
| Lint, format, typecheck | PostToolUse hooks per stack + CI | profile |

Hooks are deterministic and cannot be talked around. Rules and CLAUDE.md are instructions Claude follows. Skills are procedures loaded on demand. Agents run in their own context and return a summary.

## Changing the standards

1. Edit the file in `core/` or `profiles/<stack>/`.
2. Add a line to `CHANGELOG.md` here.
3. Tag a release (`git tag v0.2.0 && git push --tags`). Projects record the tag in `.claude/KIT_VERSION`.
4. Re-run `new-project.sh` on each project to pull the change.

Rule of thumb from Anthropic's guidance: if you find yourself writing "always do X" in CLAUDE.md, it should be a hook. If it is a 30-line procedure, it should be a skill. If it only applies to some files, it should be a path-scoped rule.

## Requirements

- Git Bash or another POSIX shell (the hooks are bash scripts; on Windows, Git Bash is enough).
- A working Python 3 on PATH (`python3`, `python`, or the `py -3` launcher). The hooks use it to parse tool input and fail closed if none is found.

## Open items

- Plugin packaging: the `core/.claude/` contents can be bundled as a Claude Code plugin for one-command install.
- Managed settings: the git and secrets hooks can be deployed through Claude Code managed settings so individual projects cannot disable them.
