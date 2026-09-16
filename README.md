# claude-dev-kit

Reusable standards for building software with Claude Code. One core set of rules, agents, skills, and hooks, plus a small profile per stack. New projects start from it; existing projects pull updates from it. Nothing in here is tied to a company or a brand: the design tokens ship with a neutral placeholder palette, and a project points at its own *design pack* for the real one.

## What is in here

```
core/                        stack-agnostic, every project gets all of this
  CLAUDE.md                  index of how we work (plan first, TDD, ask when stuck, DoD)
  .claude/agents/            six Opus subagents: architect, implementer, test-writer,
                             security-reviewer, code-reviewer, docs-writer
  .claude/skills/            /plan-project, /tdd, /definition-of-done, /update-docs
  .claude/rules/             engineering principles, when-stuck, git, docs, secrets,
                             design-system (always on), frontend (path-scoped)
  .claude/hooks/             guards: destructive git, secrets in writes, hex colours in frontend files
                             dispatchers: post-edit and stop-tests, which run each package's profile hook
                             kit.py: reads .claude/kit.json for the hooks and the script
  .claude/settings.json      permissions and hook wiring
  design/tokens.css          design tokens, the only place colors and type are defined
  design/check_logo_aspect.py  flags stretched images in .pptx and .docx output
  docs/                      templates: ARCHITECTURE, PLAN, CHANGELOG, DECISIONS (ADRs)
  .github/                   PR template
profiles/
  typescript/                web apps and services: Vitest, Playwright, ESLint, Prettier; pnpm, npm or yarn
  python/                    data, automation, CLIs, skills: pytest, Ruff, mypy; uv or pip + venv
  scripts/                   small utilities and glue, lighter gates
  <profile>/ci-job.yml       the CI job the script stitches into a new project's workflow
scripts/new-project.sh       assembles core + profiles into a project, or updates one
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

A repo with more than one package names a profile per directory:

```bash
claude-dev-kit/scripts/new-project.sh typescript=services/api,python=workers/agent ~/code/my-platform "My Platform"
```

The hooks then run each package's tools from that package's directory: an edit under `workers/agent` runs Ruff, mypy and the related pytest tests there; an edit under `services/api` runs ESLint, the package's `typecheck` script and the related Vitest files there. A file outside every package is left alone.

## Apply the kit to an existing project

Same command, pointed at the existing directory. The script adds `.claude/`, `design/`, `docs/STACK.md` and the PR template, creates `.claude/kit.json`, CI and the docs templates only where they are missing, appends its own entries to an existing `.gitignore` once, and never touches `CLAUDE.md`, `README.md` or code. Delete any template that duplicates a convention the project already has (say, `docs/DECISIONS/` when it keeps ADRs in `docs/adr/`); the script does not recreate it.

## Update a project to the latest standards

```bash
cd claude-dev-kit && git pull
scripts/new-project.sh update ~/code/existing-project
cd ~/code/existing-project && git diff .claude/ design/ docs/STACK.md
```

`update` reads the package list from the project's `.claude/kit.json` and refreshes what the kit owns (`.claude/` agents, skills, rules and hooks; `design/`; `docs/STACK.md`; the PR template). Everything else is the project's.

## `.claude/kit.json`: the project's kit settings

Created once by the script, then edited by hand. Read by the hooks on every call and by the script on every run.

```json
{
  "packages": [
    { "profile": "typescript", "path": "services/api" },
    { "profile": "python", "path": "workers/agent" }
  ],
  "design": {
    "pack": "../my-design",
    "exempt": ["theme/**", "src/legacy/tokens.css"]
  },
  "protected_branches": ["main", "master"]
}
```

| Key | What it does |
|---|---|
| `packages` | One entry per package: its profile and its directory (`.` for the root). The post-edit and stop hooks run each package's tools from there. |
| `design.pack` | A directory (relative to the project) or a git URL holding the project's brand. See *Design packs*. Empty means the kit's neutral palette. |
| `design.exempt` | Path globs the hex-colour hook skips: a vendored theme, a third-party stylesheet, a legacy file that is itself a token source. `**` spans directories; a bare directory name means everything under it. Say why in the PR when you add one. |
| `protected_branches` | Branches the git hook refuses direct commits on. An empty list turns that check off; the kit recommends leaving it on. |

## Design packs

The kit ships a neutral palette so that nothing brand-specific lives in a public repo. A project's real colours, typeface and logo live in a *design pack*: a small repo (or directory) that the script overlays onto `design/` on every run.

```
my-design/
  brand.css           :root { --brand-dark: ...; --brand-primary: ...; --font-sans: ...; }
  design-system.md    the hex table and non-web rules; replaces .claude/rules/design-system.md
  README.md           what the colours are for, measured contrast, logo usage
  logo/               logo files and a README saying which goes on which background
```

`brand.css` is appended to `design/tokens.css` as an override block, so every semantic role (`--color-*`) in the kit file resolves to the pack's values; a pack that ships a whole `tokens.css` replaces the kit's instead. Everything else lands in `design/`. The hook, the frontend rule and the Definition of Done need no changes: they read the roles, not the values. The applied pack and its revision are recorded in `.claude/DESIGN_PACK`.

Several projects for one organisation point at the same pack, so a palette change is one commit there and one `update` per project.

## How the pieces fit

| Need | Mechanism | Where |
|---|---|---|
| Plan reviewed before code | `/plan-project` skill + `architect` agent + `Status: APPROVED` gate in PLAN.md | core |
| Opus for design, review, security | `model: opus` in each agent's frontmatter | core/.claude/agents |
| Engineering principles | rules loaded every session | core/.claude/rules |
| Ask when stuck, no workarounds | when-stuck rule; agents return `STATUS: BLOCKED` | core |
| TDD | `/tdd` skill + PostToolUse hook that runs the tests related to each edit + Stop hook that refuses to finish with red tests (last-failed or changed scope by default, `KIT_TEST_SCOPE=full` for the whole suite; see the profile's STACK.md) | core dispatchers + profile hooks |
| Consistent, accessible UI | tokens.css + design pack + path-scoped frontend rule + PreToolUse hook that blocks hex colours outside tokens.css (with `design.exempt`) + image aspect checker | core |
| Git safety | PreToolUse hook (`protected_branches`) + permission deny rules | core |
| Maintainable docs | documentation rule, `/update-docs`, `docs-writer`, PR template | core |
| Lint, format, typecheck | per-profile hooks, run per package + CI | profile |

Hooks are deterministic and cannot be talked around. Rules and CLAUDE.md are instructions Claude follows. Skills are procedures loaded on demand. Agents run in their own context and return a summary.

## Changing the standards

1. Edit the file in `core/` or `profiles/<stack>/`.
2. Add a line to `CHANGELOG.md` here.
3. Tag a release (`git tag v0.2.0 && git push --tags`). Projects record the tag in `.claude/KIT_VERSION`.
4. Run `new-project.sh update` on each project to pull the change.

Rule of thumb from Anthropic's guidance: if you find yourself writing "always do X" in CLAUDE.md, it should be a hook. If it is a 30-line procedure, it should be a skill. If it only applies to some files, it should be a path-scoped rule. If it differs per project, it belongs in `.claude/kit.json`, not in a local edit to a kit-owned file (the next `update` would erase it).

## Requirements

- Git Bash or another POSIX shell (the hooks are bash scripts; on Windows, Git Bash is enough).
- A working Python 3 on PATH (`python3`, `python`, or the `py -3` launcher). The hooks use it to parse tool input and fail closed if none is found.
- Per package, whatever its profile expects: for python, `uv` with a `uv.lock`, or a `.venv` with ruff, mypy and pytest installed, or those on the PATH Python; for typescript, the package's `node_modules` (hoisted workspaces are found).

## Open items

- Plugin packaging: the `core/.claude/` contents can be bundled as a Claude Code plugin for one-command install.
- Managed settings: the git and secrets hooks can be deployed through Claude Code managed settings so individual projects cannot disable them.
- CI fragments assume uv and pnpm; a project on pip or npm edits the generated workflow once (it is project-owned after creation).
